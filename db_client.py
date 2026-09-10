import os
import uuid
import logging
import pyodbc
from dotenv import load_dotenv


load_dotenv()
logger = logging.getLogger(__name__)


ORDER_DOCUMENTS = [
    ("合规计划书", "合规计划书.docx"),
    ("文书清单", "文书清单.docx"),
]


DOCUMENT_TEMPLATE_KEYWORDS = {
    "劳动合同": ["劳动合同"],
    "劳务协议": ["劳务协议"],
    "退休返聘协议": ["退休返聘协议", "超龄人员用工协议", "超龄人员劳务合同"],
    "实习协议": ["实习协议"],
    "劳务派遣协议": ["劳务派遣协议"],
    "转正审批表": ["转正审批表", "试用期转正审批表"],
    "延长试用期协议": ["延长试用期协议"],
    "试用期辞退通知书": ["试用期辞退通知书"],
    "限期签订劳动合同通知书": ["限期签订劳动合同通知书"],
    "劳动合同变更协议书": ["劳动合同变更协议书"],
    "劳动合同续签协议": ["劳动合同续签协议"],
    "放弃续签劳动合同声明": ["放弃续签劳动合同声明", "放弃续订劳动合同声明"],
    "自愿放弃缴纳社保承诺书": ["自愿放弃缴纳社保承诺书"],
    "关于本人社会保险的说明（个人缴纳）": [
        "关于本人社会保险的说明(个人缴纳",
        "关于本人社会保险的说明（个人缴纳",
    ],
    "关于本人社会保险的说明（其他单位缴纳）": [
        "关于本人社会保险的说明(其他单位缴纳",
        "关于本人社会保险的说明（其他单位缴纳",
    ],
    "自愿放弃缴纳住房公积金承诺书": ["自愿放弃缴纳住房公积金承诺书"],
    "关于本人住房公积金的说明（其他单位缴纳）": [
        "关于本人住房公积金的说明(其他单位缴纳",
        "关于本人住房公积金的说明（其他单位缴纳",
    ],
    "工资条模板": ["工资条", "工资条模板"],
    "工伤认定申请表": ["工伤认定申请表", "工伤认定申请书"],
    "工伤赔偿协议书": ["工伤赔偿协议书", "工伤赔偿协议"],
    "工伤赔偿费用领取单": ["工伤赔偿费用领取单", "工伤赔偿费用领取表"],
    "复岗通知书": ["复岗通知书"],
    "员工手册": ["员工手册"],
    "规章制度": ["规章制度", "管理规章制度"],
    "民主程序会议签到表": ["民主程序会议签到表"],
    "规章制度确认书": ["规章制度确认书"],
    "考勤表": ["考勤表"],
    "加班审批表": ["加班审批表", "加班审批单"],
    "请假审批表": ["请假审批表", "请假审批单"],
    "年假安排通知书": ["年假安排通知书"],
    "节假日安排通知书": ["节假日安排通知书"],
    "面试登记表": ["面试登记表"],
    "无离职证明承诺书": ["无离职证明承诺书"],
    "背景调查授权书": ["背景调查授权书"],
    "员工入职承诺书": ["员工入职承诺书"],
    "工资发放账号确认书": ["工资发放账号确认书", "工资发放账号确认表"],
    "薪资调整确认单": ["薪资调整确认单"],
    "离职申请书": ["离职申请书", "离职申请表"],
    "辞退通知书": ["辞退通知书"],
    "限期返岗通知书": ["限期返岗通知书"],
    "解除劳动关系协议": ["解除劳动关系协议"],
    "离职交接单": ["离职交接单"],
    "离职证明": ["离职证明"],
    "保密协议": ["保密协议"],
    "竞业限制协议": ["竞业限制协议"],
    "培训服务期协议": ["培训服务期协议"],
}


def normalize_document_name(name: str) -> str:
    return name.strip().strip("《》").replace(" ", "")


class DBClient:
    def __init__(self):
        self.server = os.getenv("DB_SERVER")
        self.database = os.getenv("DB_DATABASE")
        self.username = os.getenv("DB_USERNAME")
        self.password = os.getenv("DB_PASSWORD")

        if not all([self.server, self.database, self.username, self.password]):
            raise ValueError("请在 .env 文件中配置数据库连接信息")

    def get_connection(self):
        """Create a SQL Server connection."""
        conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
            f"PWD={self.password};"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
        )
        return pyodbc.connect(conn_str)

    def count_document_templates(self, document_name: str) -> int:
        """Count active document templates matched by a standard document name."""
        standard_name = normalize_document_name(document_name)
        keywords = DOCUMENT_TEMPLATE_KEYWORDS.get(standard_name, [standard_name])
        keywords = [keyword for keyword in keywords if keyword]
        if not keywords:
            return 0

        conn = None
        cursor = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            where = " OR ".join(["TemplateName LIKE ?"] * len(keywords))
            params = [f"%{keyword}%" for keyword in keywords]
            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT TemplateGuid)
                FROM dbo.ent_wechat_document_template
                WHERE IsDel = 0
                  AND ({where})
                """,
                params,
            )
            row = cursor.fetchone()
            return int(row[0] or 0)

        except Exception:
            logger.exception(
                "failed to count document templates document_name=%s keywords=%s",
                document_name,
                keywords,
            )
            raise

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _upsert_document_status(
        self,
        cursor,
        meeting_id: str,
        order_id: str,
        doc_type: str,
        file_name: str,
        status: str,
        clear_file_url: bool = False,
    ) -> str:
        cursor.execute(
            """
            SELECT TOP 1 DocRecordGuid
            FROM dbo.ent_wechat_order_document WITH (UPDLOCK, HOLDLOCK)
            WHERE MeetingRecordGuid = ?
              AND OrderCustomerId = ?
              AND DocType = ?
              AND IsDel = 0
            ORDER BY CreateDate DESC
            """,
            (meeting_id, order_id, doc_type),
        )
        row = cursor.fetchone()

        if row:
            doc_guid = str(row[0])
            if clear_file_url:
                cursor.execute(
                    """
                    UPDATE dbo.ent_wechat_order_document
                    SET FileUrl = NULL,
                        FileName = ?,
                        Status = ?,
                        CreateDate = GETDATE(),
                        IsDel = 0
                    WHERE DocRecordGuid = ?
                    """,
                    (file_name, status, doc_guid),
                )
            else:
                cursor.execute(
                    """
                    UPDATE dbo.ent_wechat_order_document
                    SET FileName = ?,
                        Status = ?,
                        CreateDate = GETDATE(),
                        IsDel = 0
                    WHERE DocRecordGuid = ?
                    """,
                    (file_name, status, doc_guid),
                )
            return doc_guid

        doc_guid = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO dbo.ent_wechat_order_document
            (DocRecordGuid, MeetingRecordGuid, OrderCustomerId,
             DocType, FileUrl, FileName, Status, CreateDate, IsDel)
            VALUES (?, ?, ?, ?, NULL, ?, ?, GETDATE(), 0)
            """,
            (
                doc_guid,
                meeting_id,
                order_id,
                doc_type,
                file_name,
                status,
            ),
        )
        return doc_guid

    def prepare_task_documents(self, meeting_id: str, order_id: str, status: str = "pending"):
        """Create or reset the two generated document rows for task status display."""
        conn = None
        cursor = None

        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            for doc_type, file_name in ORDER_DOCUMENTS:
                self._upsert_document_status(
                    cursor,
                    meeting_id,
                    order_id,
                    doc_type,
                    file_name,
                    status,
                    clear_file_url=True,
                )
            conn.commit()
            logger.info(
                "task document status prepared meeting_id=%s order_id=%s status=%s",
                meeting_id,
                order_id,
                status,
            )

        except Exception:
            if conn:
                conn.rollback()
            logger.exception(
                "failed to prepare task document status meeting_id=%s order_id=%s status=%s",
                meeting_id,
                order_id,
                status,
            )
            raise

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def update_task_documents_status(self, meeting_id: str, order_id: str, status: str):
        """Update the two generated document rows with the current task status."""
        conn = None
        cursor = None

        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            for doc_type, file_name in ORDER_DOCUMENTS:
                self._upsert_document_status(
                    cursor,
                    meeting_id,
                    order_id,
                    doc_type,
                    file_name,
                    status,
                    clear_file_url=False,
                )
            conn.commit()
            logger.info(
                "task document status updated meeting_id=%s order_id=%s status=%s",
                meeting_id,
                order_id,
                status,
            )

        except Exception:
            if conn:
                conn.rollback()
            logger.exception(
                "failed to update task document status meeting_id=%s order_id=%s status=%s",
                meeting_id,
                order_id,
                status,
            )
            raise

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def save_latest_document(
        self,
        meeting_id: str,
        order_id: str,
        doc_type: str,
        file_url: str,
        file_name: str,
        status: str = "completed",
    ) -> str:
        """Insert or update the latest document record for the same business key."""
        conn = None
        cursor = None

        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT TOP 1 DocRecordGuid
                FROM dbo.ent_wechat_order_document WITH (UPDLOCK, HOLDLOCK)
                WHERE MeetingRecordGuid = ?
                  AND OrderCustomerId = ?
                  AND DocType = ?
                  AND IsDel = 0
                ORDER BY CreateDate DESC
                """,
                (meeting_id, order_id, doc_type),
            )
            row = cursor.fetchone()

            if row:
                doc_guid = str(row[0])
                cursor.execute(
                    """
                    UPDATE dbo.ent_wechat_order_document
                    SET FileUrl = ?,
                        FileName = ?,
                        Status = ?,
                        CreateDate = GETDATE(),
                        IsDel = 0
                    WHERE DocRecordGuid = ?
                    """,
                    (file_url, file_name, status, doc_guid),
                )
                action = "updated"
            else:
                doc_guid = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO dbo.ent_wechat_order_document
                    (DocRecordGuid, MeetingRecordGuid, OrderCustomerId,
                     DocType, FileUrl, FileName, Status, CreateDate, IsDel)
                    VALUES (?, ?, ?, ?, ?, ?, ?, GETDATE(), 0)
                    """,
                    (
                        doc_guid,
                        meeting_id,
                        order_id,
                        doc_type,
                        file_url,
                        file_name,
                        status,
                    ),
                )
                action = "inserted"

            conn.commit()
            logger.info(
                "document record %s doc_guid=%s meeting_id=%s order_id=%s doc_type=%s file_name=%s",
                action,
                doc_guid,
                meeting_id,
                order_id,
                doc_type,
                file_name,
            )
            return doc_guid

        except Exception:
            if conn:
                conn.rollback()
            logger.exception(
                "failed to save document record meeting_id=%s order_id=%s doc_type=%s file_name=%s",
                meeting_id,
                order_id,
                doc_type,
                file_name,
            )
            raise

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def insert_document(
        self,
        meeting_id: str,
        order_id: str,
        doc_type: str,
        file_url: str,
        file_name: str,
        status: str = "completed",
    ) -> str:
        """Backward-compatible alias. It now keeps only the latest document record."""
        return self.save_latest_document(
            meeting_id,
            order_id,
            doc_type,
            file_url,
            file_name,
            status,
        )


db_client = DBClient()
