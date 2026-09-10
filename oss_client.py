import os
import logging
from dotenv import load_dotenv
import oss2

load_dotenv()
logger = logging.getLogger(__name__)

class OSSClient:
    def __init__(self):
        access_key = os.getenv('OSS_ACCESS_KEY')
        secret_key = os.getenv('OSS_SECRET_KEY')
        endpoint = os.getenv('OSS_ENDPOINT')
        bucket_name = os.getenv('OSS_BUCKET_NAME')
        self.custom_domain = os.getenv('OSS_CUSTOM_DOMAIN')

        if not all([access_key, secret_key, endpoint, bucket_name]):
            raise ValueError("请在 .env 文件中设置 OSS_ACCESS_KEY、OSS_SECRET_KEY、OSS_ENDPOINT 和 OSS_BUCKET_NAME")

        self.auth = oss2.Auth(access_key, secret_key)
        self.bucket = oss2.Bucket(self.auth, endpoint, bucket_name)
        self.endpoint = endpoint.replace('https://', '').replace('http://', '')
        self.bucket_name = bucket_name

    def upload_file(self, local_path: str, oss_path: str) -> str:
        """上传文件到OSS并返回公共访问URL"""
        try:
            if not os.path.exists(local_path):
                raise FileNotFoundError(f"本地文件不存在: {local_path}")

            headers = {'x-oss-object-acl': 'public-read'}
            self.bucket.put_object_from_file(oss_path, local_path, headers=headers)

            # 使用自定义域名（如果配置）或默认OSS域名
            if self.custom_domain:
                url = f"{self.custom_domain.rstrip('/')}/{oss_path}"
            else:
                url = f"https://{self.bucket_name}.{self.endpoint}/{oss_path}"

            logger.info(f"OSS上传成功: {oss_path} -> {url}")
            return url
        except Exception as e:
            logger.error(f"OSS上传失败: {e}")
            raise

oss_client = OSSClient()
