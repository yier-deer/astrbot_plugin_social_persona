import os
import uuid
from typing import Optional, List

from astrbot.api import logger

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


class MemoryService:
    """基于 AstrBot 内置 FaissVecDB 的长期记忆服务，零外部依赖

    替代方案：
      mem0ai + chromadb + sentence-transformers（~2GB，安装慢）
      → AstrBot 内置 FaissVecDB + EmbeddingProvider（零额外安装）

    设计要点：
      - 向量存储：使用 AstrBot 内置的 FaissVecDB（Faiss + SQLite）
      - Embedding：使用用户在 WebUI 配置的 Embedding Provider
      - 记忆隔离：通过 metadata 中的 persona_id 字段实现
      - 降级容错：Embedding Provider 未配置时降级为空，不阻塞主流程
    """

    def __init__(self, plugin_data_path: str, memory_search_limit: int = 5):
        """
        初始化记忆服务（不创建向量数据库，首次调用时延迟初始化）

        Args:
            plugin_data_path: AstrBot 插件数据目录
            memory_search_limit: 每次检索返回的最大记忆条数
        """
        self._data_path = plugin_data_path
        self._search_limit = memory_search_limit
        self._vec_db = None
        self._initialized = False
        self._init_failed = False
        self._embedding_provider = None

    def set_embedding_provider(self, provider) -> None:
        """设置 Embedding Provider（由 main.py 从 context 获取后传入）

        Args:
            provider: AstrBot EmbeddingProvider 实例
        """
        self._embedding_provider = provider
        self._initialized = False
        self._init_failed = False
        self._vec_db = None

    async def _ensure_initialized(self) -> bool:
        """延迟初始化 FaissVecDB，失败时降级为空不阻塞主流程"""
        if self._initialized:
            return not self._init_failed
        if self._init_failed:
            return False

        if not self._embedding_provider:
            logger.warning("记忆服务：未配置 Embedding Provider，记忆功能将不可用。请在 AstrBot WebUI 中配置 Embedding 模型。")
            self._init_failed = True
            return False

        try:
            from astrbot.core.db.vec_db.faiss_impl.vec_db import FaissVecDB
            from pathlib import Path

            data_path = Path(self._data_path)
            data_path.mkdir(parents=True, exist_ok=True)

            doc_store_path = str(data_path / "memory_doc.db")
            index_store_path = str(data_path / "memory_index.faiss")

            self._vec_db = FaissVecDB(
                doc_store_path=doc_store_path,
                index_store_path=index_store_path,
                embedding_provider=self._embedding_provider,
            )
            await self._vec_db.initialize()
            self._initialized = True
            logger.info("记忆服务初始化成功（使用 AstrBot 内置 FaissVecDB）")
            return True
        except Exception as e:
            self._init_failed = True
            logger.error(f"记忆服务初始化失败，将降级为空: {e}")
            return False

    async def search(self, query: str, persona_id: str) -> List[str]:
        """
        语义检索与查询相关的记忆

        Args:
            query: 搜索关键词（如用户消息 + 事件描述）
            persona_id: 人格标识（通过 metadata 隔离不同 AI 的记忆）

        Returns:
            记忆文本列表，初始化失败返回空列表
        """
        if not await self._ensure_initialized():
            return []
        try:
            results = await self._vec_db.retrieve(
                query=query,
                k=self._search_limit,
                metadata_filters={"persona_id": persona_id},
            )
            memories = []
            for r in results:
                text = r.data.get("text", "") if isinstance(r.data, dict) else ""
                if text:
                    memories.append(text)
            return memories
        except Exception as e:
            logger.error(f"记忆检索失败: {e}")
            return []

    async def add(self, content: str, persona_id: str) -> None:
        """
        写入记忆

        Args:
            content: 要记住的内容
            persona_id: 人格标识
        """
        if not await self._ensure_initialized():
            return
        try:
            await self._vec_db.insert(
                content=content,
                metadata={"persona_id": persona_id},
                id=str(uuid.uuid4()),
            )
        except Exception as e:
            logger.error(f"记忆写入失败: {e}")

    async def add_batch(self, items: List[dict], persona_id: str) -> None:
        """
        批量写入记忆，仅持久化 importance >= 7 的高价值记忆

        Args:
            items: 记忆项列表，每项含 content 和 importance 字段
            persona_id: 人格标识
        """
        if not await self._ensure_initialized():
            return
        try:
            high_value = [
                item["content"]
                for item in items
                if item.get("importance", 0) >= 7 and item.get("content")
            ]
            if not high_value:
                return
            contents = high_value
            metadatas = [{"persona_id": persona_id} for _ in contents]
            ids = [str(uuid.uuid4()) for _ in contents]
            await self._vec_db.insert_batch(
                contents=contents,
                metadatas=metadatas,
                ids=ids,
            )
            logger.info(f"批量写入 {len(high_value)} 条关键记忆: persona={persona_id}")
        except Exception as e:
            logger.error(f"记忆批量写入失败: {e}")

    async def delete_all(self, persona_id: str) -> None:
        """
        删除指定 Persona 的所有记忆

        Args:
            persona_id: 人格标识
        """
        if not await self._ensure_initialized():
            return
        try:
            await self._vec_db.delete_documents(
                metadata_filters={"persona_id": persona_id}
            )
        except Exception as e:
            logger.error(f"记忆删除失败: {e}")
