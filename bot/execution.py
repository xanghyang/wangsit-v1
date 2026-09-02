from dataclasses import dataclass, field
import time
import json
import os
from datetime import datetime
from typing import Optional

from bot.config import Settings
from bot.logging_setup import log


@dataclass
class ExecutionResult:
    ok: bool
    status: str = ""
    order_id: str = ""
    error: str = ""
    price: float = 0.0
    size: float = 0.0
    balance: float | None = None
    filled: bool = False
    fills: list = field(default_factory=list)
    slippage_used: float = 0.0
    attempt_count: int = 0
    total_time_ms: int = 0


@dataclass 
class OrderLog:
    timestamp: str
    token_id: str
    side: str
    amount: float
    size: float
    requested_price: float
    filled_price: float
    status: str
    order_id: str
    attempt: int
    slippage: float
    error: str = ""


class ExecutionClient:
    MIN_ORDER_AMOUNT = 0.99
    MAX_ORDER_AMOUNT = 25.0
    MIN_LIQUIDITY_DEPTH = 40.0
    
    EXPONENTIAL_BACKOFF_BASE = 1
    MAX_RETRIES = 5

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._client_initialized = False
        self._tick_size_cache = {}
        self._order_log_path = "data/orders.log"
        self._circuit_broken = False
        self._circuit_reset_time = 0
        
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        os.makedirs("data", exist_ok=True)

    def reset_client(self):
        log("[EXEC] Resetting CLOB client session and credentials...")
        self._client = None
        self._client_initialized = False

    def _clob(self, force_refresh: bool = False):
        if self._client is None or force_refresh:
            from py_clob_client.client import ClobClient

            client = ClobClient(
                host=self.settings.clob_api,
                key=self.settings.private_key,
                chain_id=137,
                signature_type=1,
                funder=self.settings.proxy_wallet,
            )
            client.set_api_creds(client.create_or_derive_api_creds())
            
            log("[EXEC] CLOB client initialized successfully")
            self._client = client
            self._client_initialized = True
        return self._client

    def _is_auth_or_connection_error(self, error: str) -> bool:
        patterns = ["401", "unauthorized", "api key", "credentials", "session", "429", "connection", "disconnected", "reset"]
        err_lower = error.lower()
        return any(p in err_lower for p in patterns)

    def get_tick_size(self, token_id: str) -> float:
        if token_id in self._tick_size_cache:
            return self._tick_size_cache[token_id]
        
        try:
            tick_size = self._clob().get_tick_size(token_id)
            self._tick_size_cache[token_id] = float(tick_size)
            return float(tick_size)
        except Exception as e:
            log(f"[EXEC] Failed to get tick_size: {e}")
            if self._is_auth_or_connection_error(str(e)):
                self.reset_client()
            return 0.01

    def get_order_book(self, token_id: str) -> dict | None:
        try:
            return self._clob().get_order_book(token_id)
        except Exception as e:
            log(f"[EXEC] Failed to get order_book: {e}")
            if self._is_auth_or_connection_error(str(e)):
                self.reset_client()
            return None

    def _calculate_liquidity_depth(self, order_book: dict, side: str = "asks") -> float:
        if not order_book:
            return 0.0
        
        entries = order_book.get(side, [])
        total_depth = 0.0
        
        for entry in entries[:5]:
            if entry and len(entry) >= 2:
                price = float(entry[0])
                size = float(entry[1])
                total_depth += price * size
        
        return total_depth

    def _check_liquidity_guard(self, token_id: str, amount: float) -> tuple[bool, str]:
        if self._circuit_broken:
            if time.time() < self._circuit_reset_time:
                return False, "Circuit breaker active - waiting..."
            self._circuit_broken = False
            log("[EXEC] Circuit breaker reset")

        order_book = self.get_order_book(token_id)
        if not order_book:
            return True, "No order book - proceeding anyway"

        asks_depth = self._calculate_liquidity_depth(order_book, "asks")
        bids_depth = self._calculate_liquidity_depth(order_book, "bids")
        
        log(f"[EXEC] Liquidity - asks: ${asks_depth:.2f}, bids: ${bids_depth:.2f}")

        min_required = max(self.MIN_LIQUIDITY_DEPTH, amount * 2)
        if asks_depth < min_required:
            self._trigger_circuit_breaker()
            return False, f"Insufficient liquidity: ${asks_depth:.2f} < ${min_required:.2f} required"

        return True, "Liquidity OK"

    def _trigger_circuit_breaker(self):
        self._circuit_broken = True
        self._circuit_reset_time = time.time() + 60
        log("[EXEC] Circuit breaker triggered - pausing orders for 60s")

    def balance(self) -> float | None:
        try:
            bal = self._clob().get_balance()
            if isinstance(bal, dict) and "usdc" in bal:
                return float(bal["usdc"])
            return float(bal) if bal is not None else None
        except Exception as exc:
            log(f"[BALANCE ERROR] {exc}")
            if self._is_auth_or_connection_error(str(exc)):
                self.reset_client()
            return None

    def _validate_price(self, price: float, tick_size: float) -> float:
        if tick_size <= 0:
            tick_size = 0.01
        
        ticks = round(price / tick_size)
        validated_price = ticks * tick_size
        return min(validated_price, 0.99)

    def _calculate_dynamic_slippage(
        self,
        base_price: float,
        confidence: float = 0.5,
        timeframe: str = "5m",
        volatility: float = 0.002,
        order_book: dict = None
    ) -> float:
        base_slippage = 0.01
        
        if confidence >= 0.8:
            confidence_factor = 0.5
        elif confidence >= 0.6:
            confidence_factor = 0.75
        else:
            confidence_factor = 1.0
        
        if timeframe in ["1m", "5m"]:
            tf_factor = 1.5
        elif timeframe == "15m":
            tf_factor = 1.2
        else:
            tf_factor = 1.0
        
        vol_factor = min(abs(volatility) / 0.001, 2.0)
        
        liquidity_factor = 1.0
        if order_book:
            asks_depth = self._calculate_liquidity_depth(order_book, "asks")
            if asks_depth < 50:
                liquidity_factor = 2.0
            elif asks_depth < 100:
                liquidity_factor = 1.5
        
        dynamic_slippage = base_slippage * confidence_factor * tf_factor * vol_factor * liquidity_factor
        dynamic_slippage = min(dynamic_slippage, 0.15)
        
        return dynamic_slippage

    def _aggressive_price(self, price: float, slippage: float, tick_size: float) -> float:
        slippage_price = price * (1 + slippage)
        ticks = round(slippage_price / tick_size)
        aggressive_ticks = ticks + 5
        aggressive_price = aggressive_ticks * tick_size
        return min(aggressive_price, 0.99)

    def _enforce_position_size(self, amount: float) -> float:
        if amount < self.MIN_ORDER_AMOUNT:
            log(f"[EXEC] Amount ${amount:.2f} below min ${self.MIN_ORDER_AMOUNT} - using min")
            return self.MIN_ORDER_AMOUNT
        
        if amount > self.MAX_ORDER_AMOUNT:
            log(f"[EXEC] Amount ${amount:.2f} above max ${self.MAX_ORDER_AMOUNT} - capping")
            return self.MAX_ORDER_AMOUNT
        
        return round(amount, 2)

    def _log_order(self, order_log: OrderLog):
        log_entry = json.dumps({
            "timestamp": order_log.timestamp,
            "token_id": order_log.token_id[:20] + "...",
            "side": order_log.side,
            "amount": order_log.amount,
            "size": order_log.size,
            "requested_price": order_log.requested_price,
            "filled_price": order_log.filled_price,
            "status": order_log.status,
            "order_id": order_log.order_id[:20] + "..." if order_log.order_id else "",
            "attempt": order_log.attempt,
            "slippage": order_log.slippage,
            "error": order_log.error
        })
        
        # Issue 3.A Fix: Log rotation to prevent unbounded disk usage
        try:
            max_log_bytes = 5 * 1024 * 1024  # 5MB limit
            if os.path.exists(self._order_log_path) and os.path.getsize(self._order_log_path) > max_log_bytes:
                backup_path = f"{self._order_log_path}.1"
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                os.rename(self._order_log_path, backup_path)
        except Exception as e:
            log(f"[EXEC] Order log rotation error: {e}")

        with open(self._order_log_path, "a") as f:
            f.write(log_entry + "\n")
        
        emoji = "[OK]" if order_log.status == "filled" else "[FAIL]"
        log(f"{emoji} [ORDER LOG] {order_log.side} ${order_log.amount:.2f} @ {order_log.filled_price:.3f} (attempt {order_log.attempt})")

    def _retryable_error(self, error: str) -> bool:
        retryable_patterns = [
            "timeout",
            "rate limit",
            "429",
            "temporary",
            "network",
            "connection",
            "liquidity",
            "insufficient",
            "pending",
            "503",
            "502",
        ]
        error_lower = error.lower()
        return any(pattern in error_lower for pattern in retryable_patterns)

    def _try_order_fok_market(self, token_id: str, size: float, aggressive_price: float) -> tuple[bool, str, str, float, list]:
        try:
            from py_clob_client.clob_types import MarketOrderArgs
            from py_clob_client.order_builder.constants import BUY
            from py_clob_client.clob_types import OrderType

            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=size,
                side=BUY,
                price=aggressive_price,
                order_type=OrderType.FOK,
            )

            resp = self._clob().create_market_order(order_args)

            status = str(resp.get("status", ""))
            order_id = str(resp.get("orderID", ""))
            fills = resp.get("fills", [])
            
            if status in ["filled", "executed"] or order_id or fills:
                return True, status, order_id, aggressive_price, fills

            return False, status, order_id, aggressive_price, fills

        except Exception as exc:
            err_msg = str(exc)
            if self._is_auth_or_connection_error(err_msg):
                self.reset_client()
            return False, err_msg, "", aggressive_price, []

    def _try_order_fok_limit(self, token_id: str, size: float, aggressive_price: float) -> tuple[bool, str, str, float, list]:
        try:
            from py_clob_client.clob_types import OrderArgs
            from py_clob_client.order_builder.constants import BUY

            order_args = OrderArgs(
                token_id=token_id,
                price=aggressive_price,
                size=size,
                side=BUY,
            )

            resp = self._clob().create_order(order_args, None)

            status = str(resp.get("status", ""))
            order_id = str(resp.get("orderID", ""))
            fills = resp.get("fills", [])

            if status in ["filled", "executed"] or order_id or fills:
                return True, status, order_id, aggressive_price, fills

            return False, status, order_id, aggressive_price, fills

        except Exception as exc:
            err_msg = str(exc)
            if self._is_auth_or_connection_error(err_msg):
                self.reset_client()
            return False, err_msg, "", aggressive_price, []

    def execute_brutal_order(
        self,
        token_id: str,
        amount: float,
        price: float,
        confidence: float = 0.5,
        timeframe: str = "5m",
        volatility: float = 0.002,
        dry_run: bool = False
    ) -> ExecutionResult:
        start_time = time.time()
        
        amount = self._enforce_position_size(amount)
        
        log(f"[BRUTAL] Starting order: token={token_id[:20]}..., amount=${amount:.2f}, price={price:.3f}")
        
        liquidity_ok, liquidity_msg = self._check_liquidity_guard(token_id, amount)
        if not liquidity_ok:
            log(f"[BRUTAL] Liquidity guard failed: {liquidity_msg}")
            return ExecutionResult(
                ok=False,
                error=liquidity_msg,
                price=price,
                size=amount / price
            )

        tick_size = self.get_tick_size(token_id)
        
        size = round(amount / price, 4)
        size = round(size / tick_size) * tick_size

        order_book = self.get_order_book(token_id)
        
        dynamic_slippage = self._calculate_dynamic_slippage(
            base_price=price,
            confidence=confidence,
            timeframe=timeframe,
            volatility=volatility,
            order_book=order_book
        )
        
        if order_book:
            bids = order_book.get("bids", [])
            asks = order_book.get("asks", [])
            log(f"[BRUTAL] OrderBook - bids: {len(bids)}, asks: {len(asks)}, slippage: {dynamic_slippage:.2%}")

        if dry_run:
            log(f"[DRY RUN] Would execute: amount=${amount:.2f}, size={size}, slippage={dynamic_slippage:.2%}")
            return ExecutionResult(
                ok=True,
                status="dry_run",
                price=price * (1 + dynamic_slippage),
                size=size,
                slippage_used=dynamic_slippage,
                attempt_count=0,
                total_time_ms=int((time.time() - start_time) * 1000)
            )

        attempt = 0
        backoff = self.EXPONENTIAL_BACKOFF_BASE
        last_error = ""
        
        for attempt in range(self.MAX_RETRIES):
            aggressive_price = self._aggressive_price(price, dynamic_slippage, tick_size)
            validated_price = self._validate_price(aggressive_price, tick_size)

            # Issue 2.B Fix: Recalculate contract size dynamically per attempt based on validated execution price
            if validated_price > 0:
                current_size = round(amount / validated_price, 4)
                size = round(current_size / tick_size) * tick_size
            
            log(f"[BRUTAL] Attempt {attempt + 1}/{self.MAX_RETRIES}: price={validated_price:.3f}, size={size} (slippage={dynamic_slippage:.2%})")
            
            filled, status, order_id, exec_price, fills = self._try_order_fok_market(token_id, size, validated_price)
            
            if filled:
                elapsed_ms = int((time.time() - start_time) * 1000)
                actual_slippage = (exec_price - price) / price
                
                log(f"[BRUTAL] FOK MARKET SUCCESS @ attempt {attempt + 1}")
                log(f"   filled: ${amount:.2f} @ {exec_price:.3f} | slippage: {actual_slippage:.2%} | order_id: {order_id[:20] if order_id else 'N/A'}...")
                log(f"   total_time: {elapsed_ms}ms | fills: {len(fills)}")
                
                self._log_order(OrderLog(
                    timestamp=datetime.utcnow().isoformat(),
                    token_id=token_id,
                    side="BUY",
                    amount=amount,
                    size=size,
                    requested_price=price,
                    filled_price=exec_price,
                    status="filled",
                    order_id=order_id,
                    attempt=attempt + 1,
                    slippage=actual_slippage
                ))
                
                return ExecutionResult(
                    ok=True,
                    status=status,
                    order_id=order_id,
                    price=exec_price,
                    size=size,
                    filled=True,
                    fills=fills,
                    slippage_used=dynamic_slippage,
                    attempt_count=attempt + 1,
                    total_time_ms=elapsed_ms
                )

            log(f"[BRUTAL] FOK Market failed: {status}")
            last_error = status

            # Safety Guard against Double Execution (Issue 2.A):
            # If FOK Market failed due to a retryable/ambiguous network or timeout error,
            # DO NOT immediately submit a secondary FOK Limit order in the same attempt loop.
            if not self._retryable_error(last_error):
                filled, status, order_id, exec_price, fills = self._try_order_fok_limit(token_id, size, validated_price)
                if filled:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    actual_slippage = (exec_price - price) / price

                    log(f"[BRUTAL] FOK LIMIT SUCCESS @ attempt {attempt + 1}")
                    log(f"   filled: ${amount:.2f} @ {exec_price:.3f}")

                    self._log_order(OrderLog(
                        timestamp=datetime.utcnow().isoformat(),
                        token_id=token_id,
                        side="BUY",
                        amount=amount,
                        size=size,
                        requested_price=price,
                        filled_price=exec_price,
                        status="filled",
                        order_id=order_id,
                        attempt=attempt + 1,
                        slippage=actual_slippage
                    ))

                    return ExecutionResult(
                        ok=True,
                        status=status,
                        order_id=order_id,
                        price=exec_price,
                        size=size,
                        filled=True,
                        fills=fills,
                        slippage_used=dynamic_slippage,
                        attempt_count=attempt + 1,
                        total_time_ms=elapsed_ms
                    )

                log(f"[BRUTAL] FOK Limit failed: {status}")
                last_error = status

            if self._retryable_error(last_error) and attempt < self.MAX_RETRIES - 1:
                log(f"[BRUTAL] Retryable error, waiting {backoff}s (exponential backoff)")
                time.sleep(backoff)
                backoff *= 2

        elapsed_ms = int((time.time() - start_time) * 1000)
        log(f"💥 [BRUTAL] All {self.MAX_RETRIES} attempts failed. Last error: {last_error}")
        
        self._log_order(OrderLog(
            timestamp=datetime.utcnow().isoformat(),
            token_id=token_id,
            side="BUY",
            amount=amount,
            size=size,
            requested_price=price,
            filled_price=0,
            status="failed",
            order_id="",
            attempt=self.MAX_RETRIES,
            slippage=0,
            error=last_error
        ))
        
        self._trigger_circuit_breaker()
        
        return ExecutionResult(
            ok=False,
            error=last_error,
            price=price,
            size=size,
            attempt_count=self.MAX_RETRIES,
            total_time_ms=elapsed_ms
        )

    def buy(self, token_id: str, amount_usdc: float, price: float) -> ExecutionResult:
        return self.execute_brutal_order(
            token_id=token_id,
            amount=amount_usdc,
            price=price,
            confidence=0.5,
            timeframe="5m",
            volatility=0.002,
            dry_run=False
        )