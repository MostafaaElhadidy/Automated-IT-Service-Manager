from __future__ import annotations
from typing import Any
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    synapse_database_url: str = "postgresql+asyncpg://synapse:synapse@localhost:5432/synapse"
    synapse_database_url_ro: str = "postgresql+asyncpg://synapse:synapse@localhost:5432/synapse"

    @property
    def database_url(self) -> str:
        return self.synapse_database_url

    @property
    def database_url_ro(self) -> str:
        return self.synapse_database_url_ro

    # ── Backend ───────────────────────────────────────────────────────────────
    api_base_url: str = "http://localhost:8000"

    # ── LLM providers ─────────────────────────────────────────────────────────
    gemini_api_key: str = ""
    groq_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Per-agent model routing
    supervisor_model: str = "ollama/phi3:latest"
    intake_model: str = "ollama/phi3:latest"
    rca_model: str = "ollama/phi3:latest"
    remediation_model: str = "ollama/phi3:latest"

    # ── MCP servers ───────────────────────────────────────────────────────────
    runbook_mcp_url: str = "http://localhost:9001"
    seq_thinking_cmd: str = "npx -y @modelcontextprotocol/server-sequential-thinking"

    # ── Vector store ──────────────────────────────────────────────────────────
    chroma_dir: str = "./data/chroma"

    # ── Fast-path / determinism ───────────────────────────────────────────────
    fastpath_threshold: float = 0.82
    sim_seed: int = 42

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 480  # 8 hours

    # ── Email alerts (Resend — free tier: 3 000 emails/month) ────────────────
    resend_api_key: str = ""              # from resend.com dashboard
    alert_email_from: str = "SynapseITSM <onboarding@resend.dev>"
    alert_email_to: str = ""             # IT on-call address
    dashboard_url: str = "http://localhost:8501"

    # ── MeshCentral remote remediation ───────────────────────────────────────
    # Set MESHCENTRAL_ENABLED=true once MeshCentral is running and configured.
    # The meshctrl CLI (Node.js) must be on PATH: npm install -g meshcentral
    meshcentral_enabled: bool = False
    meshcentral_url: str = "wss://localhost:8443/control.ashx"
    meshcentral_user: str = "synapse-bot"
    meshcentral_password: str = ""          # password OR login key — one is required
    meshcentral_loginkey: str = ""          # preferred: node meshcentral --logintokenkey
    meshcentral_device_group: str = "SynapseITSM-Endpoints"
    meshcentral_verify_tls: bool = False    # True in production with real certs
    # How to invoke meshctrl — can be "meshctrl", "node /path/to/meshctrl.js", etc.
    meshcentral_meshctrl: str = "meshctrl"

    @property
    def meshcentral_meshctrl_cmd(self) -> list[str]:
        """Split meshcentral_meshctrl into tokens (supports 'node /path/to/meshctrl.js')."""
        import shlex
        return shlex.split(self.meshcentral_meshctrl)

    @property
    def meshcentral_base_url(self) -> str:
        """Base URL for meshctrl — strips /control.ashx because meshctrl appends it itself."""
        url = self.meshcentral_url
        for suffix in ("/control.ashx", "/"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
        return url

    @property
    def meshcentral_auth_args(self) -> list[str]:
        """Return auth flags for the meshctrl CLI."""
        if self.meshcentral_loginkey:
            return ["--loginkey", self.meshcentral_loginkey]
        return [
            "--loginuser", self.meshcentral_user,
            "--loginpass", self.meshcentral_password,
        ]

    # ── Tracing ───────────────────────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    def litellm_kwargs(self, agent: str) -> dict[str, Any]:
        model_map = {
            "supervisor": self.supervisor_model,
            "intake": self.intake_model,
            "rca": self.rca_model,
            "remediation": self.remediation_model,
        }
        model = model_map.get(agent, self.intake_model)
        kwargs: dict[str, Any] = {"model": model}
        if model.startswith("gemini") and self.gemini_api_key:
            kwargs["api_key"] = self.gemini_api_key
        elif model.startswith("groq") and self.groq_api_key:
            kwargs["api_key"] = self.groq_api_key
        elif model.startswith("ollama"):
            kwargs["api_base"] = self.ollama_base_url
        return kwargs


settings = Settings()
