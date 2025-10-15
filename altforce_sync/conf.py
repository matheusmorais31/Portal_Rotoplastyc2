import os
import logging

class AltForceConf:
    def __init__(self):
        self.base_url = (os.getenv("ALT_FORCE_BASE_URL", "https://integration.altforce.com.br") or "").rstrip("/")
        self.company_id = os.getenv("ALT_FORCE_COMPANY_ID")
        self.api_key = os.getenv("ALT_FORCE_API_KEY")
        # padrão: últimos 30 dias
        self.orders_default_days = int(os.getenv("ALT_FORCE_ORDERS_DEFAULT_DAYS", "30"))
        # tamanho do pedaço em dias por chamada
        self.orders_chunk_days = int(os.getenv("ALT_FORCE_ORDERS_CHUNK_DAYS", "7"))

        if not self.company_id or not self.api_key:
            logging.warning("AltForce: ALT_FORCE_COMPANY_ID/API_KEY ausentes. Defina no .env.")

    @property
    def base_company_url(self) -> str:
        return f"{self.base_url}/{self.company_id}" if self.company_id else self.base_url

config = AltForceConf()
