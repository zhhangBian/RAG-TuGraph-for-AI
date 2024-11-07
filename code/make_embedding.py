import os

os.environ["USER_AGENT"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI
from langchain.text_splitter import (
    CharacterTextSplitter,
    RecursiveCharacterTextSplitter,
    MarkdownTextSplitter,
    MarkdownHeaderTextSplitter
)
from langchain_community.document_loaders import TextLoader, WebBaseLoader
from langchain_core.output_parsers import StrOutputParser
from langchain import hub
from langchain_core.runnables import RunnablePassthrough
from langchain_core.runnables import RunnableParallel
from langchain_community.document_loaders import PyPDFDirectoryLoader
import re
from setting import *


def _get_crawl_urls(filename=None) -> dict:
    if filename is None:
        raise Exception("no crawl urls")

    # 读取successful_urls.txt中的所有链接
    with open(filename, "r") as file:
        # 假设每一行是一个链接，strip()去除换行符
        successful_urls = [line.strip() for line in file.readlines()]

    # 合并并去重 manual_links, all_links, 和 successful_urls
    all_links = list(set(successful_urls))
    print(f"the total len of crawl urls is: {len(all_links)}")

    return all_links

def _get_contents(urls):
    loader = WebBaseLoader(urls)
    documents = loader.load()

    separators = ["\n\n",  "\n",   " ",    ".",    ",",     "，",  "。", ]  # 定义分割符
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,  # 每个文本块的最大字符数
        chunk_overlap=CHUNK_OVERLAP,  # 相邻文本块之间的重叠字符数
        separators=separators,  # 用于识别文本块边界的分割符
        keep_separator=False,  # 是否保留这些分割符在文本块中
    )
    documents = text_splitter.split_documents(documents)
    return documents

def _get_markdown(root_dir):
    md_files = list()
    for dirpath, dirname, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith('.md'):
                f_path = os.path.join(dirpath, filename)
                md_files.append(f_path)

    headers_to_split_on = [
        ("#", "Header1"),
        ("##", "Header2"),
        ("###", "Header3"),
        ("####", "Header4"),
        ("#####", "Header5"),
        ("######", "Header6"),
    ]

    # 初始化MarkdownHeaderTextSplitter
    text_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=False
    )

    all_documents = list()

    for md_file in md_files:
        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # 正则匹配删去所有图片链接
            content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
            # 使用MarkdownHeaderTextSplitter进行分割
            documents = text_splitter.split_text(content)
            # 为每个文档添加源文件信息到元数据
            for doc in documents:
                doc.metadata['source_file'] = md_file
            all_documents.extend(documents)
    return all_documents

def get_docs():
    # crawl_file = "data/successful_urls.txt"
    # urls = _get_crawl_urls(crawl_file)
    # documents = _get_contents(urls)
    # return documents
    return _get_markdown('data/docs')

def _get_embedding_model():
    model_name = EMBEDDING_MODEL_NAME
    model_kwargs = {"device": "cuda"}
    # 当向量都被规范化（归一化）后，它们的范数都是1。
    # 余弦相似度的计算只需要向量的点积运算，从而减少了计算的复杂度，加快了处理速度。
    encode_kwargs = {"normalize_embeddings": True}
    embedding = HuggingFaceBgeEmbeddings(
        model_name=model_name,
        model_kwargs=model_kwargs,
        encode_kwargs=encode_kwargs,
        query_instruction="为这个句子生成表示以用于检索相关文章："
    )
    return embedding

def _create_db(documents, embedding):
    # AISS在高效相似度搜索和GPU加速方面表现出色
    # ChromaDB则提供了全面的数据库功能和分布式处理能力
    db = FAISS.from_documents(
        documents, 
        embedding=embedding
    )
    db.save_local(f"data/{EMBEDDING_DB_NAME}")

    return db

def make_embedding_db():
    # 获取原先的爬取的网页文档
    # crawl_file = "data/successful_urls.txt"
    # urls = _get_crawl_urls(crawl_file)
    # print(f"[embedding]: [{len(urls)}] urls got")

    # 将提取到的子页面分解为更小的文本块
    # documents = _get_contents(urls)

    # 读取本地存储好的markdown文件
    documents = _get_markdown('data/docs')
    print(f"[embedding]: {len(documents)} documents got")

    # 将文本转换为向量化实例
    embedding_model = _get_embedding_model()
    print(f"[embedding]: get embedding model")

    # 使用FAISS库创建一个向量数据库，它将存储从文档中提取的嵌入向量
    db = _create_db(documents, embedding_model)
    print(f"[embedding]: embedding successful!!!")
    print(f"[embedding]: !!!!!!!!!!!!!!!!!!!!!!!\n\n")
    return db

def get_retrieved_documents_string(retriever, query):
    """
    根据给定的查询，使用检索器获取相关文档，并以美观的格式返回字符串。

    参数：
    - retriever: 检索器对象，具有 get_relevant_documents 方法。
    - query: 查询字符串。

    返回值：
    - 包含格式化文档信息的字符串
    """
    # 获取相关文档
    documents = retriever.get_relevant_documents(query)
    
    # 初始化输出字符串列表
    output_lines = []
    
    # 检查是否有返回的文档
    if not documents:
        return "未找到相关的文档。"
    
    # 遍历并格式化输出
    for idx, doc in enumerate(documents, 1):
        output_lines.append(f"文档 {idx}:")
        output_lines.append("内容:")
        output_lines.append(doc.page_content)
        output_lines.append("元数据:")
        for key, value in doc.metadata.items():
            output_lines.append(f"  {key}: {value}")
        output_lines.append('-' * 40)
    
    # 将列表中的行合并为一个字符串并返回
    return '\n'.join(output_lines)

def print_retrieved_documents(retriever, query):
    # 获取相关文档
    documents = retriever.get_relevant_documents(query)
    
    # 检查是否有返回的文档
    if not documents:
        print("未找到相关的文档。")
        return
    
    # 遍历并格式化输出
    for idx, doc in enumerate(documents, 1):
        print(f"文档 {idx}:")
        print("内容:")
        print(doc.page_content)
        print("元数据:")
        for key, value in doc.metadata.items():
            print(f"  {key}: {value}")
        print('-' * 40)

if __name__ == "__main__":
    # 基于爬虫文档创建向量数据库
    db = make_embedding_db()

    # 检索时返回的相关文档数量
    search_num = SEARCH_NUM
    retriever = db.as_retriever(search_kwargs={"k": search_num})

    print_retrieved_documents(
        retriever=retriever,
        query="TuGraph 的边是否支持索引？"
    )

    # 对验证集查询文档
    with open('data/val.jsonl', 'r') as f:
        import json
        output_temp = list()
        for line in f:
            data = json.loads(line)
            question = data["input_field"]
            document_str = get_retrieved_documents_string(
                retriever=retriever,
                query=question
            )
            output_temp.append(document_str)
        for i, document_str in enumerate(output_temp):
            with open(f"data/ref/{i + 1}.txt", 'w') as fw:
                fw.write(document_str)

