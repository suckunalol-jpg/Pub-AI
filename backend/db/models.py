import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    JSON,
)
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.orm import relationship


class GUID(TypeDecorator):
    """Platform-independent UUID type. Uses CHAR(36) for SQLite, native UUID for PostgreSQL."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if not isinstance(value, uuid.UUID):
                value = uuid.UUID(value)
        return value

from db.database import Base


def gen_uuid():
    return uuid.uuid4()


# ---------- Users ----------

class User(Base):
    __tablename__ = "users"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    username = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="user")
    preferences_json = Column(JSON, default=dict)  # {theme, custom_instructions, ...}
    created_at = Column(DateTime, default=datetime.utcnow)

    api_keys = relationship("ApiKey", back_populates="user")
    conversations = relationship("Conversation", back_populates="user")
    feedbacks = relationship("Feedback", back_populates="user")
    workflows = relationship("Workflow", back_populates="user")
    knowledge_entries = relationship("KnowledgeEntry", back_populates="user")
    execution_logs = relationship("ExecutionLog", back_populates="user")
    memories = relationship("UserMemory", back_populates="user")


# ---------- API Keys ----------

class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    key_hash = Column(String(255), nullable=False)
    key_prefix = Column(String(10), nullable=False)
    name = Column(String(100), nullable=False)
    platform = Column(String(20), default="web")  # web/roblox/api
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="api_keys")


# ---------- Conversations ----------

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), default="New Chat")
    platform = Column(String(20), default="web")
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")
    agent_sessions = relationship("AgentSession", back_populates="conversation")


# ---------- Messages ----------

class Message(Base):
    __tablename__ = "messages"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    conversation_id = Column(GUID, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user/assistant/system
    content = Column(Text, nullable=False)
    model_used = Column(String(50), nullable=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
    feedbacks = relationship("Feedback", back_populates="message")


# ---------- Feedback ----------

class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    message_id = Column(GUID, ForeignKey("messages.id"), nullable=False)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    rating = Column(SmallInteger, nullable=False)  # 1=dislike, 2=like
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("Message", back_populates="feedbacks")
    user = relationship("User", back_populates="feedbacks")


# ---------- Agent Sessions ----------

class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    conversation_id = Column(GUID, ForeignKey("conversations.id"), nullable=False)
    agent_type = Column(String(50), nullable=False)
    agent_name = Column(String(100), nullable=False)
    status = Column(String(20), default="running")  # running/completed/failed
    parent_agent_id = Column(GUID, ForeignKey("agent_sessions.id"), nullable=True)
    config = Column(JSON, default=dict)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    conversation = relationship("Conversation", back_populates="agent_sessions")
    parent = relationship("AgentSession", remote_side=[id])


# ---------- Workflows ----------

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    steps = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="workflows")
    runs = relationship("WorkflowRun", back_populates="workflow")


# ---------- Workflow Runs ----------

class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    workflow_id = Column(GUID, ForeignKey("workflows.id"), nullable=False)
    status = Column(String(20), default="running")
    step_results = Column(JSON, default=dict)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    workflow = relationship("Workflow", back_populates="runs")


# ---------- Knowledge Entries ----------

class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    source_type = Column(String(50), default="manual")  # qa/doc/code/manual
    embedding_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="knowledge_entries")


# ---------- Execution Logs ----------

class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    language = Column(String(30), nullable=False)
    code = Column(Text, nullable=False)
    output = Column(Text, nullable=True)
    exit_code = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="execution_logs")


# ---------- User Memory (per-user learning) ----------

class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    memory_type = Column(String(50), nullable=False)  # preference/fact/skill/pattern/correction
    key = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)
    confidence = Column(Integer, default=50)  # 0-100 confidence score
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, default=datetime.utcnow)
    source_message_id = Column(GUID, ForeignKey("messages.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="memories")


# ---------- Intent Log (Bayesian learning) ----------

class IntentLog(Base):
    __tablename__ = "intent_logs"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    message_content = Column(Text, nullable=False)
    predicted_intent = Column(String(100), nullable=False)
    actual_intent = Column(String(100), nullable=True)  # corrected by feedback
    confidence = Column(Integer, default=50)
    was_correct = Column(Boolean, nullable=True)
    features = Column(JSON, default=dict)  # extracted features for learning
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Learning Signal (RL reward tracking) ----------

class LearningSignal(Base):
    __tablename__ = "learning_signals"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(GUID, ForeignKey("conversations.id"), nullable=False)
    action_type = Column(String(50), nullable=False)  # tool_use/response/code_gen/agent_spawn
    action_detail = Column(JSON, default=dict)
    reward = Column(Integer, default=0)  # -1 to +1 mapped from feedback
    context_hash = Column(String(64), nullable=True)  # hash of context for dedup
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Registered Models (Multi-Model Support) ----------

class RegisteredModel(Base):
    """Tracks registered AI model endpoints that Pub AI can route inference to.

    provider_type:
        - "huggingface"       : HuggingFace Inference API (OpenAI-compatible /v1/chat/completions)
        - "ollama"            : Ollama local server (/api/chat)
        - "openai-compatible" : Any server exposing the OpenAI chat completions API
    """
    __tablename__ = "registered_models"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    name = Column(String(100), unique=True, nullable=False)
    provider_type = Column(String(30), nullable=False)  # huggingface / ollama / openai-compatible
    endpoint_url = Column(String(500), nullable=False)
    api_token = Column(String(500), nullable=True)  # nullable for local models (e.g. Ollama)
    model_identifier = Column(String(200), nullable=False)  # model name sent to the endpoint
    is_active = Column(Boolean, default=False)  # only one model should be active at a time
    config = Column(JSON, default=dict)  # extra provider-specific config (e.g. default temp)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)


# ---------- Team Templates ----------

class TeamTemplate(Base):
    """Saved team configurations that can be reused."""
    __tablename__ = "team_templates"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=True)  # nullable for system presets
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    agent_specs = Column(JSON, nullable=False)  # List of {type, role, task?}
    is_preset = Column(Boolean, default=False)  # True for system presets
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------- Custom Agent Types ----------

class CustomAgentType(Base):
    """User-defined agent types with custom system prompts and configurations."""
    __tablename__ = "custom_agent_types"

    id = Column(GUID, primary_key=True, default=gen_uuid)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    type_key = Column(String(50), nullable=False)  # e.g., "my-debugger"
    role = Column(String(200), nullable=False)
    specialty = Column(Text, nullable=False)
    system_prompt_extra = Column(Text, nullable=True)  # Additional prompt injected
    max_iterations = Column(Integer, default=50)
    temperature = Column(Integer, default=4)  # stored as int * 10 (e.g., 4 = 0.4)
    created_at = Column(DateTime, default=datetime.utcnow)
