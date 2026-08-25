"""文档分割服务模块 - 基于 LangChain 的智能文档分割

支持文件类型: md, txt, pdf, docx
各类型分片策略:
  - md:  标题结构分割(H1/H2) → 递归字符分割 → 合并小片段
  - txt: 递归字符分割
  - pdf: PyPDFLoader 逐页提取文本 → 递归字符分割
  - docx: Docx2txtLoader 提取纯文本 → 递归字符分割
"""

from pathlib import Path

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from loguru import logger

from app.config import config


class DocumentSplitterService:
    """文档分割服务 - 使用 LangChain 的分割器"""

    # 支持的文件扩展名映射
    SUPPORTED_EXTENSIONS = {
        ".txt": "纯文本",
        ".md": "Markdown",
        ".pdf": "PDF 文档",
        ".docx": "Word 文档",
    }

    def __init__(self):
        """初始化文档分割服务"""
        self.chunk_size = config.chunk_max_size
        self.chunk_overlap = config.chunk_overlap

        # Markdown 标题分割器 (只按一级和二级标题分割，减少分片数)
        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "h1"),
                ("##", "h2"),
                # 不再按三级标题分割，避免过度碎片化
            ],
            strip_headers=False,  # 保留标题在内容中
        )

        # 递归字符分割器 (用于二次分割，使用更大的chunk_size)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size * 2,  # 加倍chunk_size，减少分片数
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

        logger.info(
            f"文档分割服务初始化完成, chunk_size={self.chunk_size}, "
            f"secondary_chunk_size={self.chunk_size * 2}, "
            f"overlap={self.chunk_overlap}, "
            f"支持类型: {list(self.SUPPORTED_EXTENSIONS.keys())}"
        )

    # ─────────────────────── 公共方法 ───────────────────────

    def extract_text(self, file_path: str) -> str:
        """
        统一入口：根据文件扩展名自动选择提取方式

        Args:
            file_path: 文件路径

        Returns:
            str: 提取的文本内容
        """
        ext = Path(file_path).suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: {ext}，支持: {list(self.SUPPORTED_EXTENSIONS.keys())}")

        extracted = self._extract_text_from_file(file_path, ext)

        if not extracted or not extracted.strip():
            logger.warning(f"文件文本提取为空: {file_path}")
            return ""

        logger.info(f"文本提取完成: {file_path} ({ext}), 长度: {len(extracted)} 字符")
        return extracted

    def split_document(
        self,
        content: str,
        file_path: str = "",
        extra_metadata: dict[str, str] | None = None,
    ) -> list[Document]:
        """
        智能分割文档 (根据文件类型选择分割器)

        Args:
            content: 文档文本内容（已提取）
            file_path: 文件路径 (用于判断类型和元数据)

        Returns:
            List[Document]: 文档分片列表
        """
        ext = Path(file_path).suffix.lower()

        if ext == ".md":
            return self.split_markdown(content, file_path, extra_metadata)
        elif ext in (".txt", ".pdf", ".docx"):
            return self.split_text(content, file_path, extra_metadata)
        else:
            logger.warning(f"未知文件类型 {ext}，使用默认文本分割器")
            return self.split_text(content, file_path, extra_metadata)

    # ─────────────────────── 分片方法 ───────────────────────

    def split_markdown(
        self,
        content: str,
        file_path: str = "",
        extra_metadata: dict[str, str] | None = None,
    ) -> list[Document]:
        """
        分割 Markdown 文档 (两阶段分割 + 合并小片段)

        策略:
          第一阶段: MarkdownHeaderTextSplitter 按 H1/H2 标题切分
          第二阶段: RecursiveCharacterTextSplitter 按字符数再切分
          第三阶段: 合并 < 300 字符的碎片到相邻片段

        Args:
            content: Markdown 内容
            file_path: 文件路径 (用于元数据)

        Returns:
            List[Document]: 文档分片列表
        """
        if not content or not content.strip():
            logger.warning(f"Markdown 文档内容为空: {file_path}")
            return []

        try:
            # 第一阶段: 按标题分割
            md_docs = self.markdown_splitter.split_text(content)

            # 第二阶段: 按大小进一步分割
            docs_after_split = self.text_splitter.split_documents(md_docs)

            # 第三阶段: 合并太小的分片 (< 300字符)
            final_docs = self._merge_small_chunks(docs_after_split, min_size=300)

            # 添加文件路径元数据
            for doc in final_docs:
                doc.metadata["_source"] = file_path
                doc.metadata["_extension"] = ".md"
                doc.metadata["_file_name"] = Path(file_path).name
                if extra_metadata:
                    doc.metadata.update(extra_metadata)

            logger.info(f"Markdown 分割完成: {file_path} -> {len(final_docs)} 个分片")
            return final_docs

        except Exception as e:
            logger.error(f"Markdown 分割失败: {file_path}, 错误: {e}")
            raise

    def split_text(
        self,
        content: str,
        file_path: str = "",
        extra_metadata: dict[str, str] | None = None,
    ) -> list[Document]:
        """
        分割纯文本文档

        策略:
          RecursiveCharacterTextSplitter 按 \\n\\n → \\n → 。 → ， 优先级递归切分

        适用类型: .txt, .pdf, .docx (提取后的纯文本)

        Args:
            content: 文本内容
            file_path: 文件路径 (用于元数据)

        Returns:
            List[Document]: 文档分片列表
        """
        if not content or not content.strip():
            logger.warning(f"文本文档内容为空: {file_path}")
            return []

        try:
            ext = Path(file_path).suffix.lower() if file_path else ".txt"

            metadata = {
                "_source": file_path,
                "_extension": ext,
                "_file_name": Path(file_path).name if file_path else "",
            }
            if extra_metadata:
                metadata.update(extra_metadata)

            docs = self.text_splitter.create_documents(
                texts=[content],
                metadatas=[metadata],
            )

            logger.info(f"文本分割完成: {file_path} -> {len(docs)} 个分片")
            return docs

        except Exception as e:
            logger.error(f"文本分割失败: {file_path}, 错误: {e}")
            raise

    # ─────────────────────── 私有方法 ───────────────────────

    def _extract_text_from_file(self, file_path: str, ext: str) -> str:
        """
        内部：根据扩展名选择对应的提取方式

        Args:
            file_path: 文件路径
            ext: 小写扩展名 (如 .md, .pdf)

        Returns:
            str: 提取的文本
        """
        path = Path(file_path)

        if ext == ".md" or ext == ".txt":
            # 纯文本文件：直接 UTF-8 读取
            return path.read_text(encoding="utf-8")

        elif ext == ".pdf":
            # PDF 文件：使用 PyPDFLoader 逐页提取后拼接
            return self._extract_pdf(file_path)

        elif ext == ".docx":
            # Word 文件：使用 Docx2txtLoader 提取纯文本
            return self._extract_docx(file_path)

        else:
            raise ValueError(f"无法提取的文件类型: {ext}")

    def _extract_pdf(self, file_path: str) -> str:
        """
        PDF 文本提取

        使用 langchain_community 的 PyPDFLoader:
          - 调用 pypdf 库逐页读取 PDF 文本流
          - 每页作为独立 Document 返回
          - 本方法将所有页拼接为单个文本，页间以双换行分隔

        Args:
            file_path: PDF 文件路径

        Returns:
            str: 拼接后的全部文本
        """
        try:
            loader = PyPDFLoader(file_path)
            pages = loader.load()
            logger.debug(f"PDF 加载完成: {file_path}, 共 {len(pages)} 页")

            # 拼接所有页面文本，页间加双换行
            texts = []
            for i, page in enumerate(pages):
                page_text = page.page_content.strip()
                if page_text:
                    texts.append(page_text)

            full_text = "\n\n".join(texts)
            logger.debug(f"PDF 文本拼接完成: {len(full_text)} 字符")
            return full_text

        except Exception as e:
            logger.error(f"PDF 文本提取失败: {file_path}, 错误: {e}")
            raise RuntimeError(f"PDF 文本提取失败: {e}") from e

    def _extract_docx(self, file_path: str) -> str:
        """
        Word (.docx) 文本提取

        使用 langchain_community 的 Docx2txtLoader:
          - 底层调用 docx2txt 库解析 .docx XML 结构
          - 提取纯文本内容，不保留样式/表格/图片
          - loader.load() 返回 1 个 Document，page_content 即为全文

        Args:
            file_path: Docx 文件路径

        Returns:
            str: 提取的纯文本
        """
        try:
            loader = Docx2txtLoader(file_path)
            docs = loader.load()
            logger.debug(f"Docx 加载完成: {file_path}, 返回 {len(docs)} 个文档片段")

            # Docx2txtLoader 通常返回 1 个 Document
            text = docs[0].page_content if docs else ""
            logger.debug(f"Docx 文本提取完成: {len(text)} 字符")
            return text

        except Exception as e:
            logger.error(f"Docx 文本提取失败: {file_path}, 错误: {e}")
            raise RuntimeError(f"Docx 文本提取失败: {e}") from e

    def _merge_small_chunks(
        self, documents: list[Document], min_size: int = 300
    ) -> list[Document]:
        """
        合并太小的分片

        Args:
            documents: 文档列表
            min_size: 最小分片大小 (字符数)

        Returns:
            List[Document]: 合并后的文档列表
        """
        if not documents:
            return []

        merged_docs = []
        current_doc = None

        for doc in documents:
            doc_size = len(doc.page_content)

            if current_doc is None:
                # 第一个文档
                current_doc = doc
            elif doc_size < min_size and len(current_doc.page_content) < self.chunk_size * 2:
                # 当前文档太小且合并后不会太大，则合并
                current_doc.page_content += "\n\n" + doc.page_content
                # 保留主文档的元数据
            else:
                # 保存当前文档，开始新文档
                merged_docs.append(current_doc)
                current_doc = doc

        # 添加最后一个文档
        if current_doc is not None:
            merged_docs.append(current_doc)

        return merged_docs


# 全局单例
document_splitter_service = DocumentSplitterService()
