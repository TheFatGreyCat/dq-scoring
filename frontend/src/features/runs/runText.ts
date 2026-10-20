import { useI18n } from "../../lib/i18n";

const TEXT = {
  vi: {
    mine_title: "Công việc của tôi",
    mine_hint: "Chỉ gồm các lượt đánh giá do bạn gửi. Trang tự cập nhật khi còn công việc đang chạy.",
    none: "Chưa có công việc nào.",
    stale: "Mất kết nối. Hiển thị dữ liệu cập nhật lần cuối lúc {time}; công việc không bị coi là thất bại.",
    refresh: "Làm mới",
    timeline: "Dòng thời gian",
    timeline_empty: "Chưa có sự kiện.",
    load_more: "Tải thêm sự kiện",
    attempt: "Lần chạy {n}",
    submitted: "Đã gửi",
    attempts: "Số lần chạy",
    EVENT_RUN_QUEUED: "Đã xếp hàng",
    EVENT_RUN_CLAIMED: "Worker đã nhận",
    EVENT_RUN_RUNNING: "Đang chạy",
    EVENT_RUN_SUCCEEDED: "Hoàn tất",
    EVENT_RUN_FAILED: "Thất bại",
    EVENT_RUN_CANCELLED: "Đã hủy",
    EVENT_RUN_EVENT: "Sự kiện khác",
  },
  en: {
    mine_title: "My jobs",
    mine_hint: "Only evaluation runs you submitted. This page refreshes while any job is active.",
    none: "No jobs yet.",
    stale: "Connection lost. Showing the last update from {time}; jobs are not treated as failed.",
    refresh: "Refresh",
    timeline: "Timeline",
    timeline_empty: "No events yet.",
    load_more: "Load more events",
    attempt: "Attempt {n}",
    submitted: "Submitted",
    attempts: "Attempts",
    EVENT_RUN_QUEUED: "Queued",
    EVENT_RUN_CLAIMED: "Claimed by worker",
    EVENT_RUN_RUNNING: "Running",
    EVENT_RUN_SUCCEEDED: "Completed",
    EVENT_RUN_FAILED: "Failed",
    EVENT_RUN_CANCELLED: "Cancelled",
    EVENT_RUN_EVENT: "Other event",
  },
} as const;

export type RunTextKey = keyof (typeof TEXT)["en"];

export function useRunText() {
  const { lang } = useI18n();
  return (key: RunTextKey, params: Record<string, string | number> = {}) =>
    Object.entries(params).reduce((text: string, [k, v]) => text.replaceAll(`{${k}}`, String(v)), TEXT[lang][key]);
}
