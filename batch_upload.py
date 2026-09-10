import os
import argparse
from upload_documents import upload_and_save


def batch_upload(
    folder_path: str,
    meeting_id: str,
    order_id: str,
    doc_type: str = None,
    oss_folder: str = "meeting_documents"
):
    """
    批量上传文件夹中的所有文件
    
    :param folder_path: 本地文件夹路径
    :param meeting_id: 会议记录GUID
    :param order_id: 订单ID
    :param doc_type: 文档类型（如果为None，将从文件名推断）
    :param oss_folder: OSS存储文件夹
    """
    if not os.path.exists(folder_path):
        print(f"错误：文件夹不存在: {folder_path}")
        return
    
    files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    
    if not files:
        print("警告：文件夹中没有文件")
        return
    
    print(f"找到 {len(files)} 个文件待上传")
    print("=" * 60)
    
    success_count = 0
    fail_count = 0
    results = []
    
    for filename in files:
        local_path = os.path.join(folder_path, filename)
        
        # 从文件名推断文档类型
        if doc_type is None:
            if "合规计划" in filename or "合规计划书" in filename:
                file_doc_type = "合规计划书"
            elif "文书清单" in filename or "清单" in filename:
                file_doc_type = "文书清单"
            else:
                file_doc_type = "其他文档"
        else:
            file_doc_type = doc_type
        
        print(f"\n正在处理: {filename}")
        print(f"文档类型: {file_doc_type}")
        
        result = upload_and_save(
            local_file_path=local_path,
            meeting_id=meeting_id,
            order_id=order_id,
            doc_type=file_doc_type,
            oss_folder=oss_folder
        )
        
        results.append(result)
        
        if result["success"]:
            success_count += 1
            print(f"✅ 成功")
        else:
            fail_count += 1
            print(f"❌ 失败: {result['error']}")
    
    print("\n" + "=" * 60)
    print("批量上传完成！")
    print(f"总文件数: {len(files)}")
    print(f"成功: {success_count}")
    print(f"失败: {fail_count}")
    
    if fail_count > 0:
        print("\n失败文件列表:")
        for r in results:
            if not r["success"]:
                print(f"  - {r['file_name']}: {r['error']}")


def main():
    parser = argparse.ArgumentParser(description="批量上传文档到OSS并保存到数据库")
    parser.add_argument("--folder", required=True, help="本地文件夹路径")
    parser.add_argument("--meeting-id", required=True, help="会议记录GUID")
    parser.add_argument("--order-id", required=True, help="订单ID")
    parser.add_argument("--doc-type", help="文档类型（如：合规计划书、文书清单），不指定则自动推断")
    parser.add_argument("--oss-folder", default="meeting_documents", help="OSS存储文件夹")
    
    args = parser.parse_args()
    
    print("批量上传文档")
    print("=" * 60)
    print(f"文件夹路径: {args.folder}")
    print(f"会议ID: {args.meeting_id}")
    print(f"订单ID: {args.order_id}")
    print(f"文档类型: {args.doc_type or '自动推断'}")
    print(f"OSS文件夹: {args.oss_folder}")
    print("=" * 60)
    
    batch_upload(
        folder_path=args.folder,
        meeting_id=args.meeting_id,
        order_id=args.order_id,
        doc_type=args.doc_type,
        oss_folder=args.oss_folder
    )


if __name__ == "__main__":
    main()
