import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { governanceTranslations } from "./governanceTranslations";
import { privacyTranslations } from "./privacyTranslations";
import { surfaceTranslations } from "./surfaceTranslations";
export type Language = "vi" | "en";

export const DICTIONARY = {
  vi: {
    ...governanceTranslations.vi,
    ...privacyTranslations.vi,
    ...surfaceTranslations.vi,
    // Navigation
    "nav.overview": "Tổng quan",
    "nav.assets": "Dữ liệu & Snapshot",
    "nav.rulesets": "Tập luật (Rulesets)",
    "nav.policies": "Chính sách (Policies)",
    "nav.templates": "Kho luật & Mẫu",
    "nav.runs": "Lượt đánh giá (Runs)",
    "nav.assessments": "Kết quả & Thẻ điểm",
    "nav.settings": "Cài đặt hệ thống",
    "nav.open": "Mở điều hướng",
    "nav.close": "Đóng điều hướng",
    "nav.main": "Điều hướng chính",
    "nav.drawer": "Bảng điều hướng",
    "theme.light": "Sáng",
    "theme.dark": "Tối",

    // Header & Actions
    "header.title": "DQ Scoring",
    "header.subtitle": "Hệ thống Đánh giá Chất lượng Dữ liệu",
    "header.sign_out": "Đăng xuất",
    "header.signed_in_as": "Đăng nhập với:",
    "header.theme.to_light": "Chuyển sang giao diện sáng",
    "header.theme.to_dark": "Chuyển sang giao diện tối",
    "header.lang.switch": "Chuyển đổi ngôn ngữ (VI / EN)",
    "btn.save": "Lưu lại",
    "btn.cancel": "Hủy",
    "btn.create": "Tạo mới",
    "btn.apply": "Áp dụng",
    "btn.back": "Quay lại",
    "btn.copy": "Sao chép ID",
    "btn.copied": "Đã sao chép!",
    "btn.submit": "Gửi phê duyệt",
    "btn.approve": "Phê duyệt",
    "btn.trigger_run": "Bắt đầu chạy",
    "btn.open": "Mở",
    "btn.close": "Đóng",

    // Domains
    "domain.FINANCE": "Tài chính & Giao dịch",
    "domain.RETAIL": "Bán lẻ & Thương mại điện tử",
    "domain.TRANSPORTATION": "Vận tải & Di chuyển đô thị",
    "domain.HEALTHCARE": "Y tế & Sức khỏe",
    "domain.GENERAL": "Dữ liệu chung (Master Data)",

    // Dimensions
    "dim.COMPLETENESS": "Tính đầy đủ (Completeness)",
    "dim.ACCURACY": "Tính chính xác (Accuracy)",
    "dim.CONSISTENCY": "Tính nhất quán (Consistency)",
    "dim.TIMELINESS": "Tính kịp thời (Timeliness)",
    "dim.UNIQUENESS": "Tính duy nhất (Uniqueness)",
    "dim.VALIDITY": "Tính hợp lệ (Validity)",

    // Statuses
    "status.DRAFT": "Bản nháp",
    "status.PENDING_APPROVAL": "Chờ phê duyệt",
    "status.ACTIVE": "Đang hoạt động",
    "status.DEPRECATED": "Đã ngưng dùng",
    "status.QUEUED": "Đang xếp hàng",
    "status.LEASED": "Đã cấp phát",
    "status.RUNNING": "Đang tính toán",
    "status.SUCCEEDED": "Thành công",
    "status.FAILED": "Thất bại",
    "status.CANCELLED": "Đã hủy",

    // Settings
    "settings.title": "Cài đặt hệ thống",
    "settings.subtitle": "Thông tin tài khoản, quyền hạn, kết nối hạ tầng và tùy chọn giao diện.",
    "settings.profile.title": "Thông tin tài khoản & Phiên",
    "settings.profile.email": "Email người dùng",
    "settings.profile.role": "Vai trò hệ thống (Role)",
    "settings.profile.tenant": "Mã tổ chức (Tenant ID)",
    "settings.appearance.title": "Tùy biến hiển thị & Ngôn ngữ",
    "settings.appearance.theme": "Chế độ giao diện (Theme)",
    "settings.appearance.lang": "Ngôn ngữ hiển thị (Language)",
    "settings.infra.title": "Hạ tầng & Kết nối lưu trữ",
    "settings.infra.data_root": "Thư mục dữ liệu (Data Root)",
    "settings.infra.spark": "Công cụ tính toán Spark",
    "settings.infra.db": "Cơ sở dữ liệu lưu trữ (Postgres RLS)",
    "settings.security.title": "Bảo mật & Phân quyền",
    "settings.security.four_eyes": "Nguyên tắc phê duyệt độc lập (Four-Eyes)",
    "settings.security.lockout": "Chính sách bảo vệ đăng nhập (Lockout)",

    // Templates & Survey
    "templates.title": "Kho luật & Mẫu quy tắc (Templates)",
    "templates.subtitle": "Duyệt các rule dựng sẵn, template theo ngành và khảo sát gợi ý nhanh.",
    "templates.tab.rules": "Kho Rule mẫu",
    "templates.tab.rulesets": "Mẫu Ruleset theo Domain",
    "templates.tab.policies": "Mẫu Scoring Policy",
    "templates.wizard.btn": "Khảo sát gợi ý nhanh cho dữ liệu mới",
    "templates.wizard.title": "Trợ lý khảo sát & Gợi ý bộ quy tắc DQ",
    "templates.wizard.desc": "Chỉ với 3 bước đơn giản, hệ thống sẽ tự động đề xuất bộ rule và chính sách phù hợp nhất cho dữ liệu của bạn.",
    "templates.wizard.step1": "1. Chọn lĩnh vực dữ liệu (Domain)",
    "templates.wizard.step2": "2. Chọn mục tiêu chất lượng trọng tâm",
    "templates.wizard.step3": "3. Bộ quy tắc & chính sách gợi ý",
    "templates.wizard.apply_btn": "Áp dụng và tạo Ruleset này",
    "common.loading": "Đang tải…",
    "common.empty": "Chưa có dữ liệu.",
    "common.search": "Tìm kiếm",
    "common.reset": "Xóa bộ lọc",
    "common.previous": "Trang trước",
    "common.next": "Trang sau",
    "common.all": "Tất cả",
    "common.retry": "Thử lại",
    "common.count": "{count} kết quả",
    "common.name": "Tên",
    "common.status": "Trạng thái",
    "common.unknown": "Không xác định",
    "common.format": "Định dạng",
    "common.created": "Thời gian tạo",
    "assets.import": "Nhập dữ liệu",
    "assets.new": "Tạo dữ liệu mới",
    "assets.existing": "Dữ liệu đã có",
    "import.file": "Tệp CSV / Parquet / JSONL phẳng",
    "import.object": "Chọn object MinIO",
    "import.prefix": "Tiền tố object",
    "import.delimiter": "Dấu phân cách CSV",
    "import.upload": "Tải lên và kiểm tra",
    "import.progress": "Đã tải {done} / {total} byte",
    "import.register": "Xác nhận đăng ký snapshot",
    "import.abort": "Hủy nhập",
    "import.resume": "Chọn lại cùng tệp để tiếp tục tải phần còn thiếu.",
    "import.ack": "Tôi xác nhận tệp chỉ có một cột.",
    "import.mapping": "Tên cột theo thứ tự",
    "import.configure": "Áp dụng ánh xạ và kiểm tra lại",
    "import.success": "Snapshot bất biến đã đăng ký.",
    "import.unsupported": "Chỉ hỗ trợ CSV, Parquet và JSONL phẳng.",
    "preview.title": "Xem trước dữ liệu đã che thông tin",
    "preview.sample": "Chỉ hiển thị tối đa 50 dòng mẫu; tìm kiếm không quét toàn bộ dữ liệu.",
    "preview.rows": "{count} dòng",
    "preview.columns": "{count} cột",
    "preview.column_search": "Lọc cột",
    "preview.null": "NULL (thiếu giá trị)",
    "preview.empty": "Chuỗi rỗng",
    "preview.schema": "Lược đồ và ánh xạ",
    "preview.hash": "SHA-256 dữ liệu gốc",
    "preview.size": "Kích thước gốc",
    "recommend.review": "Gợi ý từ mẫu, cần xem xét trước khi áp dụng.",
    "recommend.rules": "Gợi ý luật",
    "recommend.policy": "Tạo chính sách",
    "recommend.run": "Tạo lượt đánh giá",
    "status.INITIATED": "Đã khởi tạo",
    "status.UPLOADING": "Đang tải lên",
    "status.STAGED": "Chờ kiểm tra",
    "status.VERIFYING": "Đang kiểm tra toàn bộ",
    "status.VERIFIED": "Dữ liệu hợp lệ",
    "status.REGISTERED": "Đã đăng ký",
    "status.REJECTED": "Dữ liệu bị từ chối",
    "status.ABORTED": "Đã hủy nhập",
    "error.NESTED_DATA_UNSUPPORTED": "JSONL phải phẳng; không hỗ trợ đối tượng hoặc mảng lồng nhau.",
    "error.EMPTY_DATASET": "Tệp không có bản ghi dữ liệu.",
    "error.MALFORMED_CSV": "CSV sai cấu trúc; kiểm tra số cột và dấu ngoặc kép.",
    "error.MALFORMED_JSONL": "Mỗi dòng phải là một đối tượng JSON hợp lệ và phẳng.",
    "error.UNSUPPORTED_FORMAT": "Định dạng này không được hỗ trợ.",
    "error.DUPLICATE_COLUMN_NAME": "Tên cột trùng nhau; ánh xạ lại theo thứ tự.",
    "error.EMPTY_COLUMN_NAME": "Tên cột trống; ánh xạ lại theo thứ tự.",
    "error.OBJECT_CHANGED": "Dữ liệu đã thay đổi; bắt đầu phiên nhập mới.",
    "error.IMPORT_EXPIRED": "Phiên nhập đã hết hạn; bắt đầu phiên mới.",
    "error.STORAGE_UNAVAILABLE": "Không truy cập được lưu trữ; thử lại sau.",
    "error.PREVIEW_UNAVAILABLE": "Snapshot cũ không có bản xem trước.",
    "error.IMPORT_STATE_CONFLICT": "Thao tác không phù hợp với trạng thái hiện tại.",
    "error.RESOURCE_NOT_FOUND": "Không tìm thấy tài nguyên trong workspace.",
    "error.ASSET_NAME_CONFLICT": "Tên đã tồn tại; chọn dữ liệu đã có.",
    "error.generic": "Yêu cầu thất bại. Kiểm tra dữ liệu và thử lại.",
    "run.active_required": "Chọn snapshot và cấu hình đã được người khác phê duyệt.",
    "run.snapshot": "Snapshot dữ liệu",
    "run.outliers": "Cột phát hiện ngoại lệ (tùy chọn)",
    "run.advisory": "Chỉ tư vấn; không thay đổi điểm hoặc cổng chất lượng.",
    "run.unknown": "Chưa rõ yêu cầu đã được nhận hay chưa. Thử lại dùng cùng khóa, không tạo lượt chạy thứ hai.",
    "run.history": "Lịch sử đánh giá",
    "run.title": "Lượt đánh giá",
    "run.refresh": "Trạng thái tự cập nhật khi trang này đang mở.",
    "run.reconnecting": "Mất kết nối. Đang kết nối lại; hiển thị trạng thái gần nhất.",
    "run.id": "Mã lượt chạy",
    "run.updated": "Cập nhật lần cuối",
    "run.ready": "Kết quả đánh giá đã sẵn sàng",
    "run.failed": "Lượt đánh giá thất bại",
    "run.unpublished": "Không công bố kết quả hoặc cổng chất lượng cho lượt chạy này.",
    "common.from": "Từ thời điểm",
    "common.to": "Đến trước thời điểm",
    "overview.desc": "Dữ liệu, cấu hình và kết quả đã lưu trong workspace.",
    "common.not_found": "Không tìm thấy trang",
  },
  en: {
    ...governanceTranslations.en,
    ...privacyTranslations.en,
    ...surfaceTranslations.en,
    // Navigation
    "nav.overview": "Overview",
    "nav.assets": "Assets & Snapshots",
    "nav.rulesets": "Rulesets",
    "nav.policies": "Policies",
    "nav.templates": "Rule & Template Catalog",
    "nav.runs": "Runs",
    "nav.assessments": "Assessments",
    "nav.settings": "Settings",
    "nav.open": "Open navigation",
    "nav.close": "Close navigation",
    "nav.main": "Main navigation",
    "nav.drawer": "Navigation drawer",
    "theme.light": "Light",
    "theme.dark": "Dark",

    // Header & Actions
    "header.title": "DQ Scoring",
    "header.subtitle": "Data Quality Assessment",
    "header.sign_out": "Sign out",
    "header.signed_in_as": "Signed in as:",
    "header.theme.to_light": "Switch to light theme",
    "header.theme.to_dark": "Switch to dark theme",
    "header.lang.switch": "Switch language (VI / EN)",
    "btn.save": "Save",
    "btn.cancel": "Cancel",
    "btn.create": "Create",
    "btn.apply": "Apply",
    "btn.back": "Back",
    "btn.copy": "Copy ID",
    "btn.copied": "Copied!",
    "btn.submit": "Submit for approval",
    "btn.approve": "Approve",
    "btn.trigger_run": "Trigger evaluation run",
    "btn.open": "Open",
    "btn.close": "Close",

    // Domains
    "domain.FINANCE": "Finance & Transactions",
    "domain.RETAIL": "Retail & E-Commerce",
    "domain.TRANSPORTATION": "Transportation & Mobility",
    "domain.HEALTHCARE": "Healthcare & Life Sciences",
    "domain.GENERAL": "General (Master Data)",

    // Dimensions
    "dim.COMPLETENESS": "Completeness",
    "dim.ACCURACY": "Accuracy",
    "dim.CONSISTENCY": "Consistency",
    "dim.TIMELINESS": "Timeliness",
    "dim.UNIQUENESS": "Uniqueness",
    "dim.VALIDITY": "Validity",

    // Statuses
    "status.DRAFT": "Draft",
    "status.PENDING_APPROVAL": "Pending Approval",
    "status.ACTIVE": "Active",
    "status.DEPRECATED": "Deprecated",
    "status.QUEUED": "Queued",
    "status.LEASED": "Leased",
    "status.RUNNING": "Running",
    "status.SUCCEEDED": "Succeeded",
    "status.FAILED": "Failed",
    "status.CANCELLED": "Cancelled",

    // Settings
    "settings.title": "System Settings",
    "settings.subtitle": "Account credentials, permissions, infrastructure and UI preferences.",
    "settings.profile.title": "Account & Session Context",
    "settings.profile.email": "User Email",
    "settings.profile.role": "Assigned System Role",
    "settings.profile.tenant": "Tenant Organization ID",
    "settings.appearance.title": "Appearance & Localization",
    "settings.appearance.theme": "Theme Mode",
    "settings.appearance.lang": "Display Language",
    "settings.infra.title": "Infrastructure & Storage Connectivity",
    "settings.infra.data_root": "Mounted Data Root Path",
    "settings.infra.spark": "Vectorized PySpark Engine",
    "settings.infra.db": "PostgreSQL Store (with RLS)",
    "settings.security.title": "Security & Governance Rules",
    "settings.security.four_eyes": "Four-Eyes Principle Enforcement",
    "settings.security.lockout": "Brute-force Lockout Policy",

    // Templates & Survey
    "templates.title": "Rule & Scoring Templates Catalog",
    "templates.subtitle": "Explore standard rules, domain-based template packages and smart recommender wizard.",
    "templates.tab.rules": "Rule Catalog",
    "templates.tab.rulesets": "Domain Rulesets",
    "templates.tab.policies": "Domain Scoring Policies",
    "templates.wizard.btn": "Quick Onboarding & Recommendation Wizard",
    "templates.wizard.title": "Smart Data Quality Recommender",
    "templates.wizard.desc": "Complete 3 fast steps to get an auto-generated ruleset and scoring policy tailored to your domain.",
    "templates.wizard.step1": "1. Select Data Domain",
    "templates.wizard.step2": "2. Select Core Quality Goals",
    "templates.wizard.step3": "3. Recommended Ruleset & Policy",
    "templates.wizard.apply_btn": "Apply and Create This Ruleset",
    "common.loading": "Loading…",
    "common.empty": "No data yet.",
    "common.search": "Search",
    "common.reset": "Reset filters",
    "common.previous": "Previous",
    "common.next": "Next",
    "common.all": "All",
    "common.retry": "Retry",
    "common.count": "{count} results",
    "common.name": "Name",
    "common.status": "Status",
    "common.unknown": "Unknown",
    "common.format": "Format",
    "common.created": "Created",
    "assets.import": "Import dataset",
    "assets.new": "New asset",
    "assets.existing": "Existing asset",
    "import.file": "CSV / Parquet / flat JSONL file",
    "import.object": "Select MinIO object",
    "import.prefix": "Object prefix",
    "import.delimiter": "CSV delimiter",
    "import.upload": "Upload and validate",
    "import.progress": "Uploaded {done} / {total} bytes",
    "import.register": "Confirm snapshot registration",
    "import.abort": "Abort import",
    "import.resume": "Select the same file to resume missing parts.",
    "import.ack": "I confirm this file has only one column.",
    "import.mapping": "Ordered column names",
    "import.configure": "Apply mapping and revalidate",
    "import.success": "Immutable snapshot registered.",
    "import.unsupported": "Only CSV, Parquet and flat JSONL are supported.",
    "preview.title": "Redacted dataset preview",
    "preview.sample": "At most 50 sample rows; search does not scan the full dataset.",
    "preview.rows": "{count} rows",
    "preview.columns": "{count} columns",
    "preview.column_search": "Filter columns",
    "preview.null": "NULL (missing value)",
    "preview.empty": "Empty string",
    "preview.schema": "Schema and mapping",
    "preview.hash": "Raw SHA-256",
    "preview.size": "Raw size",
    "recommend.review": "Sample-based suggestions require review.",
    "recommend.rules": "Suggested rules",
    "recommend.policy": "Create policy",
    "recommend.run": "Create evaluation",
    "status.INITIATED": "Initialized",
    "status.UPLOADING": "Uploading",
    "status.STAGED": "Awaiting validation",
    "status.VERIFYING": "Validating full dataset",
    "status.VERIFIED": "Validated",
    "status.REGISTERED": "Registered",
    "status.REJECTED": "Rejected",
    "status.ABORTED": "Aborted",
    "error.NESTED_DATA_UNSUPPORTED": "JSONL must be flat; nested objects or arrays are unsupported.",
    "error.EMPTY_DATASET": "The file contains no data records.",
    "error.MALFORMED_CSV": "Malformed CSV; check field counts and quoting.",
    "error.MALFORMED_JSONL": "Each line must be a valid flat JSON object.",
    "error.UNSUPPORTED_FORMAT": "This format is unsupported.",
    "error.DUPLICATE_COLUMN_NAME": "Duplicate columns; provide ordered unique names.",
    "error.EMPTY_COLUMN_NAME": "Blank columns; provide ordered names.",
    "error.OBJECT_CHANGED": "Data changed; start a new import session.",
    "error.IMPORT_EXPIRED": "Import session expired; start a new session.",
    "error.STORAGE_UNAVAILABLE": "Storage unavailable; try again later.",
    "error.PREVIEW_UNAVAILABLE": "Preview is unavailable for this historical snapshot.",
    "error.IMPORT_STATE_CONFLICT": "Operation is not allowed in the current state.",
    "error.RESOURCE_NOT_FOUND": "Resource not found in this workspace.",
    "error.ASSET_NAME_CONFLICT": "Name exists; select the existing asset.",
    "error.generic": "Request failed. Check the input and retry.",
    "run.active_required": "Choose a snapshot and configurations approved by another user.",
    "run.snapshot": "Dataset snapshot",
    "run.outliers": "Outlier columns (optional)",
    "run.advisory": "Advisory only; score and quality gate are unchanged.",
    "run.unknown": "Outcome unknown. Retrying uses the same key and does not create a second run.",
    "run.history": "Evaluation history",
    "run.title": "Evaluation run",
    "run.refresh": "Status refreshes automatically while this page is open.",
    "run.reconnecting": "Connection lost. Reconnecting; the last known status is shown.",
    "run.id": "Run ID",
    "run.updated": "Last updated",
    "run.ready": "Assessment ready",
    "run.failed": "Run failed",
    "run.unpublished": "No assessment or quality gate was published for this run.",
    "common.from": "Created from",
    "common.to": "Created before",
    "overview.desc": "Persisted data, configurations and results in this workspace.",
    "common.not_found": "Page not found",
  },
};
export type TranslationKey = keyof typeof DICTIONARY.vi;
export type TranslationParams = Record<string, string | number>;
const englishKeys: Record<TranslationKey, string> = DICTIONARY.en;
void englishKeys;

interface I18nContextType {
  lang: Language;
  setLang: (lang: Language) => void;
  toggleLang: () => void;
  t: (key: TranslationKey, params?: TranslationParams) => string;
}

const I18nContext = createContext<I18nContextType | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Language>(() => {
    try {
      const saved = localStorage.getItem("dq_language");
      return saved === "en" || saved === "vi" ? saved : "vi";
    } catch { return "vi"; }
  });

  const setLang = (next: Language) => {
    setLangState(next);
    try { localStorage.setItem("dq_language", next); } catch { /* Current-page language still works. */ }
    document.documentElement.lang = next;
  };

  const toggleLang = () => {
    setLang(lang === "vi" ? "en" : "vi");
  };

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const t = (key: TranslationKey, params?: TranslationParams): string => {
    let text: string = DICTIONARY[lang][key];
    Object.entries(params ?? {}).forEach(([name, value]) => { text = text.replaceAll(`{${name}}`, String(value)); });
    return text;
  };

  return (
    <I18nContext.Provider value={{ lang, setLang, toggleLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextType {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("I18nProvider is required.");
  }
  return ctx;
}
