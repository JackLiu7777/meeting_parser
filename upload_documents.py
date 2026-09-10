import os
import argparse
from oss_client import oss_client
from db_client import db_client


def upload_document_to_oss(local_file_path: str, oss_folder: str = "meeting_documents") -> str:
    """
    上传本地文件到OSS
    
    :param local_file_path: 本地文件路径
    :param oss_folder: OSS存储文件夹
    :return: OSS文件URL
    """
    if not os.path.exists(local_file_path):
        raise FileNotFoundError(f"文件不存在: {local_file_path}")
    
    file_name = os.path.basename(local_file_path)
    oss_path = f"{oss_folder}/{file_name}"
    
    print(f"正在上传文件: {local_file_path} -> {oss_path}")
    url = oss_client.upload_file(local_file_path, oss_path)
    print(f"上传成功: {url}")
    
    return url


def save_to_database(
    meeting_id: str,
    order_id: str,
    doc_type: str,
    file_url: str,
    file_name: str,
    status: str = "completed"
) -> str:
    """
    保存文件记录到数据库
    
    :param meeting_id: 会议记录GUID
    :param order_id: 订单ID
    :param doc_type: 文档类型
    :param file_url: OSS文件URL
    :param file_name: 文件名
    :param status: 状态（completed/pending）
    :return: 文档记录GUID
    """
    print(f"正在保存到数据库: doc_type={doc_type}, file_name={file_name}")
    doc_guid = db_client.save_latest_document(
        meeting_id=meeting_id,
        order_id=order_id,
        doc_type=doc_type,
        file_url=file_url,
        file_name=file_name,
        status=status
    )
    print(f"保存成功: doc_guid={doc_guid}")
    
    return doc_guid


def upload_and_save(
    local_file_path: str,
    meeting_id: str,
    order_id: str,
    doc_type: str,
    oss_folder: str = "meeting_documents",
    status: str = "completed"
) -> dict:
    """
    上传文件到OSS并保存到数据库
    
    :param local_file_path: 本地文件路径
    :param meeting_id: 会议记录GUID
    :param order_id: 订单ID
    :param doc_type: 文档类型
    :param oss_folder: OSS存储文件夹
    :param status: 状态
    :return: 结果字典
    """
    try:
        file_name = os.path.basename(local_file_path)
        
        # 上传到OSS
        file_url = upload_document_to_oss(local_file_path, oss_folder)
        
        # 保存到数据库
        doc_guid = save_to_database(
            meeting_id=meeting_id,
            order_id=order_id,
            doc_type=doc_type,
            file_url=file_url,
            file_name=file_name,
            status=status
        )
        
        return {
            "success": True,
            "doc_guid": doc_guid,
            "file_name": file_name,
            "file_url": file_url,
            "meeting_id": meeting_id,
            "order_id": order_id,
            "doc_type": doc_type
        }
    
    except Exception as e:
        print(f"上传失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_name": os.path.basename(local_file_path)
        }


def main():
    parser = argparse.ArgumentParser(description="上传文档到OSS并保存到数据库")
    parser.add_argument("--file", required=True, help="本地文件路径")
    parser.add_argument("--meeting-id", required=True, help="会议记录GUID")
    parser.add_argument("--order-id", required=True, help="订单ID")
    parser.add_argument("--doc-type", required=True, help="文档类型（如：合规计划书、文书清单）")
    parser.add_argument("--oss-folder", default="meeting_documents", help="OSS存储文件夹")
    parser.add_argument("--status", default="completed", help="文档状态")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"文件路径: {args.file}")
    print(f"会议ID: {args.meeting_id}")
    print(f"订单ID: {args.order_id}")
    print(f"文档类型: {args.doc_type}")
    print(f"OSS文件夹: {args.oss_folder}")
    print(f"状态: {args.status}")
    print("=" * 60)
    
    result = upload_and_save(
        local_file_path=args.file,
        meeting_id=args.meeting_id,
        order_id=args.order_id,
        doc_type=args.doc_type,
        oss_folder=args.oss_folder,
        status=args.status
    )
    
    print("=" * 60)
    if result["success"]:
        print("✅ 操作成功！")
        print(f"文档GUID: {result['doc_guid']}")
        print(f"文件URL: {result['file_url']}")
    else:
        print("❌ 操作失败！")
        print(f"错误信息: {result['error']}")


if __name__ == "__main__":
    main()
