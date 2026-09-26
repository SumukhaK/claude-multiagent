"""Single source of truth for all tunable configuration, loaded from .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for the multiagent system, sourced from environment/.env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Local LLM serving: Planner + Coder agents (llama.cpp)
    llama_cpp_dir: str = r"E:\LLMCPP"
    llama_model_path: str = r"E:\LLMCPP\DeepSeek-R1-Distill-Qwen-1.5B-UD-Q4_K_XL.gguf"
    llama_server_host: str = "127.0.0.1"
    llama_server_port: int = 8080
    llama_gpu_layers: int = 999
    llama_context_size: int = 8192
    llama_parallel_slots: int = 2
    llama_flash_attn: bool = True
    llama_kv_cache_type: str = "q8_0"
    llama_threads: int = 6
    llama_constrain_json: bool = False  # grammar-constrain Planner/Coder output to their JSON schemas
    llama_log_path: str = "logs/llama-server.log"  # server stdout/stderr (gitignored)

    # Local LLM serving: Tool agent (Ollama, CPU-only)
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_tool_model: str = "qwen2.5:7b-instruct"
    ollama_tool_use_gpu: bool = False
    ollama_tool_context_size: int = 4096

    # Memory layer (mem0, local): embeddings via Ollama, vector store on disk
    memory_path: str = ".memory"
    memory_embedding_model: str = "nomic-embed-text"
    memory_embedding_dims: int = 768
    memory_recall_limit: int = 3
    memory_recall_max_chars: int = 600

    # Orchestrator safety limits
    max_retries_per_step: int = 2
    max_orchestrator_steps: int = 25

    # Observability
    log_level: str = "INFO"
    otel_enabled: bool = True
    otel_exporter: str = "console"

    # Optional evaluation (off by default; free tier only, needs the user's own keys)
    langsmith_enabled: bool = False
    langsmith_api_key: str = ""

    # Sandbox
    project_sandbox_root: str = "."


def get_settings() -> Settings:
    """Return a freshly-loaded Settings instance."""
    return Settings()
