import { useI18n } from "../../lib/i18n";

const TEXT = {
  vi: {
    adapters: "Kết nối adapter",
    adapter_database: "Cơ sở dữ liệu", adapter_storage: "Lưu trữ đối tượng", adapter_spark_compute: "Spark compute", adapter_advisory_gateway: "Cổng AI tư vấn",
    state_up: "Hoạt động", state_degraded: "Suy giảm", state_down: "Ngừng", state_unknown: "Chưa rõ", state_off: "Đang tắt", state_not_configured: "Chưa cấu hình",
    source_probe: "kiểm tra trực tiếp", source_worker_heartbeat: "heartbeat worker", source_configuration: "cấu hình (không gọi thử)",
    checked: "Quan sát lúc", never: "Chưa từng", last_success: "Thành công gần nhất", stale: "Dữ liệu cũ",
    cluster_scope: "Số liệu toàn cụm Spark, dùng chung mọi workspace; không phải tiến độ của một yêu cầu.",
    requests: "Yêu cầu trong workspace", creator: "Người gửi (ID)", submitted: "Đã gửi", owner_unknown: "Không rõ",
    mine_marker: "bạn", open: "Chi tiết",
    spark_title: "Quan sát Spark của lần chạy", spark_observed: "Đang quan sát", spark_stale: "Dữ liệu cũ", spark_ended: "Đã kết thúc", spark_unknown: "Chưa quan sát được",
    attempt: "Lần chạy", jobs: "Job", tasks: "Task", application: "Ứng dụng Spark", group: "Nhóm job", request_state: "Trạng thái yêu cầu",
    spark_note: "Trạng thái yêu cầu và quan sát Spark là hai nguồn riêng; thiếu quan sát không có nghĩa là thất bại.",
  },
  en: {
    adapters: "Adapter connections",
    adapter_database: "Database", adapter_storage: "Object storage", adapter_spark_compute: "Spark compute", adapter_advisory_gateway: "Advisory AI gateway",
    state_up: "Up", state_degraded: "Degraded", state_down: "Down", state_unknown: "Unknown", state_off: "Off", state_not_configured: "Not configured",
    source_probe: "live probe", source_worker_heartbeat: "worker heartbeat", source_configuration: "configuration (never probed)",
    checked: "Observed", never: "Never", last_success: "Last success", stale: "Stale",
    cluster_scope: "Cluster-wide Spark figures shared by all workspaces; not the progress of any single request.",
    requests: "Workspace requests", creator: "Submitter (ID)", submitted: "Submitted", owner_unknown: "Unknown",
    mine_marker: "you", open: "Details",
    spark_title: "Run Spark observation", spark_observed: "Observed", spark_stale: "Stale", spark_ended: "Ended", spark_unknown: "Not observed",
    attempt: "Attempt", jobs: "Jobs", tasks: "Tasks", application: "Spark application", group: "Job group", request_state: "Request state",
    spark_note: "Request state and Spark observation are separate sources; a missing observation does not mean failure.",
  },
} as const;
export type OperationsTextKey = keyof (typeof TEXT)["en"];

export function useOperationsText() {
  const { lang } = useI18n();
  return (key: OperationsTextKey) => TEXT[lang][key];
}
