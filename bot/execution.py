from dataclasses import dataclass

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


class ExecutionClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    def _clob(self):
        if self._client is None:
            from py_clob_client.client import ClobClient

            client = ClobClient(
                host=self.settings.clob_api,
                key=self.settings.private_key,
                chain_id=137,
                signature_type=1,
                funder=self.settings.proxy_wallet,
            )
            client.set_api_creds(client.create_or_derive_api_creds())
            self._client = client
        return self._client

    def balance(self) -> float | None:
        try:
            bal = self._clob().get_balance()
            if isinstance(bal, dict) and "usdc" in bal:
                return float(bal["usdc"])
            return float(bal) if bal is not None else None
        except Exception as exc:
            log(f"[BALANCE ERROR] {exc}")
            return None

    def buy(self, token_id: str, amount_usdc: float, price: float) -> ExecutionResult:
        try:
            from py_clob_client.clob_types import OrderArgs
            from py_clob_client.order_builder.constants import BUY

            taker_price = min(round(price + self.settings.taker_slippage, 2), 0.99)
            if taker_price > self.settings.price_max + self.settings.taker_slippage + 1e-9:
                return ExecutionResult(False, error="taker price exceeds configured guard")
            size = round(amount_usdc / price, 2)
            resp = self._clob().create_and_post_order(OrderArgs(
                token_id=token_id,
                price=taker_price,
                size=size,
                side=BUY,
            ))
            status = str(resp.get("status", ""))
            order_id = str(resp.get("orderID", ""))
            log(f"   BUY OK: {status} | order {order_id[:20]}...")
            return ExecutionResult(True, status=status, order_id=order_id, price=taker_price, size=size)
        except Exception as exc:
            log(f"   BUY failed: {exc}")
            return ExecutionResult(False, error=str(exc))

