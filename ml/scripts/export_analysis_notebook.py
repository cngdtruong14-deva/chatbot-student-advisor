import json
from pathlib import Path

def create_notebook():
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Báo cáo Phân tích Dữ liệu OULAD & Đánh giá So sánh Mô hình Huấn luyện\n",
                    "\n",
                    "**Dự án**: Intelligent Student Advisor Platform (Capstone)  \n",
                    "**Mô hình được đánh giá**: `oulad-risk-logistic-regression` (Phiên bản: `final-002`)  \n",
                    "**Bộ dữ liệu**: Open University Learning Analytics Dataset (OULAD)  \n",
                    "**Mục tiêu**: Dự đoán nguy cơ sinh viên Không hoàn thành môn học (`non_completion_at_end`: Fail hoặc Withdrawn) tại mốc **Ngày 28** (kết thúc 4 tuần đầu).  \n",
                    "**Mục đích sổ tay**: Cung cấp số liệu so sánh đối chuẩn (Dummy vs Random Forest vs Logistic Regression), phân tích tầm quan trọng của các đặc trưng học tập (VLE interactions, assessments, prior retakes, credits), và đánh giá độ tin cậy xác suất phục vụ cố vấn học vụ.\n"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import json\n",
                    "import numpy as np\n",
                    "import pandas as pd\n",
                    "from pathlib import Path\n",
                    "\n",
                    "# Đường dẫn artifact được phê duyệt\n",
                    "REPO_ROOT = Path.cwd()\n",
                    "while not (REPO_ROOT / 'artifacts').exists() and REPO_ROOT.parent != REPO_ROOT:\n",
                    "    REPO_ROOT = REPO_ROOT.parent\n",
                    "\n",
                    "ARTIFACT_DIR = REPO_ROOT / 'artifacts' / 'approved' / 'final-002'\n",
                    "if not ARTIFACT_DIR.exists():\n",
                    "    ARTIFACT_DIR = Path('/artifacts/approved/final-002')\n",
                    "\n",
                    "with open(ARTIFACT_DIR / 'manifest.json', 'r', encoding='utf-8') as f:\n",
                    "    manifest = json.load(f)\n",
                    "\n",
                    "with open(ARTIFACT_DIR / 'metrics.json', 'r', encoding='utf-8') as f:\n",
                    "    metrics = json.load(f)\n",
                    "\n",
                    "with open(ARTIFACT_DIR / 'explanation_config.json', 'r', encoding='utf-8') as f:\n",
                    "    explanation_config = json.load(f)\n",
                    "\n",
                    "print(f\"=== MÔ HÌNH: {manifest['model_id']} ({manifest['model_version']}) ===\")\n",
                    "print(f\"Domain: {manifest['domain_id']} | Cutoff: Ngày {manifest['cutoff_day']} | Target: {manifest['target_id']}\")\n",
                    "print(f\"Huấn luyện lúc: {manifest['trained_at']} | Source commit: {manifest['source_commit']}\")\n"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 1. Bảng so sánh các mô hình trên tập phát triển (Dev Set Validation)\n",
                    "\n",
                    "Quy mô tập Dev: **349 sinh viên** (Tỷ lệ rớt/rút môn thực tế: **40.40%**).  \n",
                    "Quy tắc chọn mô hình: Lựa chọn mô hình đạt **Average Precision (AP)** cao nhất trên Dev; tối ưu ngưỡng cảnh báo (*Alert Threshold*) theo F1 score.\n"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": 2,
                "metadata": {},
                "outputs": [],
                "source": [
                    "comparison_rows = []\n",
                    "for item in metrics['comparison_dev']:\n",
                    "    m = item['metrics']\n",
                    "    comparison_rows.append({\n",
                    "        'Mô hình': item['model'].replace('_', ' ').title(),\n",
                    "        'Average Precision (AP)': round(m['average_precision'], 4),\n",
                    "        'ROC-AUC': round(m['roc_auc'], 4),\n",
                    "        'F1-Score': round(m['f1'], 4),\n",
                    "        'Recall (Độ nhạy)': round(m['recall'], 4),\n",
                    "        'Precision (Độ chuẩn)': round(m['precision'], 4),\n",
                    "        'Brier Score (MSE)': round(m['brier'], 4),\n",
                    "        'Ngưỡng tối ưu (Threshold)': round(m['threshold'], 4)\n",
                    "    })\n",
                    "\n",
                    "df_comparison = pd.DataFrame(comparison_rows)\n",
                    "df_comparison\n"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "### Nhận xét đánh giá Dev Set:\n",
                    "- **Logistic Regression** vượt trội cả **Dummy Baseline** (+57.1% AP) và **Random Forest** (+2.7% AP).\n",
                    "- **Brier Score** của Logistic Regression đạt 0.2082 (thấp nhất trong cả 3 mô hình), phản ánh sai số bình phương xác suất nhỏ nhất.\n",
                    "- **Recall đạt 87.94%** ở ngưỡng cảnh báo `threshold = 0.32`, đảm bảo phần lớn sinh viên có nguy cơ rớt môn đều được phát hiện sớm.\n"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 2. Đánh giá tổng quát hóa trên tập kiểm thử độc lập (Test Set Evaluation)\n",
                    "\n",
                    "Tập Test gồm **329 sinh viên** hoàn toàn tách biệt (*student-disjoint split*, seed 42) để kiểm chứng khả năng tổng quát hóa, không bị rò rỉ dữ liệu (*data leakage*).\n"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": 3,
                "metadata": {},
                "outputs": [],
                "source": [
                    "t = metrics['test_metrics']\n",
                    "test_summary = pd.DataFrame([{\n",
                    "    'Số mẫu kiểm thử (N)': t['sample_count'],\n",
                    "    'Tỷ lệ rủi ro thực tế': f\"{round(t['positive_prevalence'] * 100, 2)}%\",\n",
                    "    'Average Precision (AP)': round(t['average_precision'], 4),\n",
                    "    'ROC-AUC': round(t['roc_auc'], 4),\n",
                    "    'Recall': round(t['recall'], 4),\n",
                    "    'Precision': round(t['precision'], 4),\n",
                    "    'F1-Score': round(t['f1'], 4),\n",
                    "    'Brier Score': round(t['brier'], 4)\n",
                    "}])\n",
                    "test_summary\n"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": 4,
                "metadata": {},
                "outputs": [],
                "source": [
                    "cm = np.array(t['confusion_matrix'])\n",
                    "df_cm = pd.DataFrame(cm, \n",
                    "    index=['Thực tế: ĐẬU/HOÀN THÀNH (0)', 'Thực tế: RỚT/RÚT MÔN (1)'],\n",
                    "    columns=['Dự đoán: ĐẬU (0)', 'Dự đoán: RỚT (1)'])\n",
                    "print('=== MA TRẬN NHẦM LẪN (CONFUSION MATRIX TRÊN TẬP TEST N=329) ===')\n",
                    "print(f\"- True Negatives (TN): {cm[0, 0]} (Dự đoán Đậu - Thực tế Đậu)\")\n",
                    "print(f\"- False Positives (FP): {cm[0, 1]} (Cảnh báo nhầm - Thực tế Đậu)\")\n",
                    "print(f\"- False Negatives (FN): {cm[1, 0]} (Bỏ sót - Thực tế Rớt)\")\n",
                    "print(f\"- True Positives (TP): {cm[1, 1]} (Cảnh báo đúng - Thực tế Rớt)\")\n",
                    "df_cm\n"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 3. Phân tích đặc trưng & Trọng số mô hình (Feature Analysis & Weights)\n",
                    "\n",
                    "Các đặc trưng được trích xuất từ dữ liệu OULAD tại mốc Ngày 28 và chuẩn hóa qua `StandardScaler`.\n",
                    "Hệ số hồi quy (*Regression Coefficient*) biểu thị mức độ ảnh hưởng đến Log-odds của nguy cơ rớt môn.\n"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": 5,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import joblib\n",
                    "pipeline = joblib.load(ARTIFACT_DIR / 'pipeline.joblib')\n",
                    "scaler = pipeline.named_steps['scaler']\n",
                    "clf = pipeline.named_steps['classifier']\n",
                    "\n",
                    "features = manifest['feature_order']\n",
                    "weights = clf.coef_[0]\n",
                    "means = scaler.mean_\n",
                    "stds = scaler.scale_\n",
                    "\n",
                    "descriptions = [\n",
                    "    'Số lần đã từng học lại môn này trước đây',\n",
                    "    'Tổng số tín chỉ đăng ký học đồng thời trong kỳ',\n",
                    "    'Tổng số lượt click trên hệ thống VLE (ngày 0-28)',\n",
                    "    'Số ngày có tương tác VLE (ngày 0-28)',\n",
                    "    'Số bài đánh giá/bài tập đã nộp (ngày 0-28)',\n",
                    "    'Số ngày trôi qua từ lần tương tác VLE cuối đến ngày 28'\n",
                    "]\n",
                    "\n",
                    "df_features = pd.DataFrame({\n",
                    "    'Đặc trưng (Feature)': features,\n",
                    "    'Mô tả': descriptions,\n",
                    "    'Hệ số hồi quy (Coefficient)': [round(w, 4) for w in weights],\n",
                    "    'Tác động': ['Tăng rủi ro (+)' if w > 0 else 'Giảm rủi ro (-)' for w in weights],\n",
                    "    'Giá trị trung bình (Mean)': [round(m, 2) for m in means],\n",
                    "    'Độ lệch chuẩn (Std)': [round(s, 2) for s in stds]\n",
                    "}).sort_values(by='Hệ số hồi quy (Coefficient)', key=abs, ascending=False)\n",
                    "\n",
                    "print(f\"Điểm chặn mô hình (Intercept): {round(clf.intercept_[0], 4)}\")\n",
                    "df_features\n"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "### Phân tích ý nghĩa học vụ:\n",
                    "1. **`vle_active_days_0_28` (Hệ số: -0.5730)**: Đặc trưng bảo vệ có tác động mạnh nhất. Sinh viên vào học đều đặn nhiều ngày (thói quen học tập phân bổ) có nguy cơ rớt môn giảm rất mạnh.\n",
                    "2. **`assessment_submitted_count_0_28` (Hệ số: -0.2185)**: Nộp bài kiểm tra/bài tập sớm trong 4 tuần đầu là chỉ dấu tích cực cho cam kết hoàn thành khóa học.\n",
                    "3. **`num_of_prev_attempts` (Hệ số: +0.2178)**: Đã từng học lại là tín hiệu cảnh báo rủi ro cao. Nhóm này cần được cố vấn theo dõi sát sao.\n",
                    "4. **`studied_credits` (Hệ số: +0.1984)**: Tải học tập quá nặng (nhiều tín chỉ cùng lúc) làm tăng xác suất bỏ môn do quá tải.\n"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 4. Đánh giá độ hiệu chuẩn xác suất (Probability Calibration)\n",
                    "\n",
                    "Độ hiệu chuẩn thể hiện sự tương quan giữa xác suất mô hình dự đoán và tỷ lệ sinh viên thực tế gặp rủi ro trong từng phân nhóm.\n"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": 6,
                "metadata": {},
                "outputs": [],
                "source": [
                    "cal = metrics['test_metrics']['calibration']\n",
                    "df_cal = pd.DataFrame({\n",
                    "    'Xác suất dự đoán trung bình': [round(p, 4) for p in cal['mean_predicted_probability']],\n",
                    "    'Tỷ lệ rủi ro thực tế': [round(f, 4) for f in cal['fraction_positive']]\n",
                    "})\n",
                    "print('=== BẢNG HIỆU CHUẨN XÁC SUẤT TRÊN TẬP TEST ===')\n",
                    "df_cal\n"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 5. Ranh giới sử dụng an toàn (Contract 1.0.0 & Governance Policy)\n",
                    "\n",
                    "- **Chỉ dùng cho mục đích nghiên cứu OULAD**: Mô hình `final-002` được phê duyệt phục vụ đối chuẩn nghiên cứu công khai.\n",
                    "- **Không áp dụng suy luận cho sinh viên thực tế (NTTU / DEMO-1)**: Khi hệ thống nhận diện yêu cầu dự đoán cho sinh viên DEMO, hệ thống sẽ từ chối an toàn với mã `409 MODEL_DOMAIN_MISMATCH` nhằm ngăn chặn thiên lệch mô hình giữa môi trường học từ xa Open University tại Anh và chương trình đào tạo tín chỉ tại Việt Nam.\n",
                    "- **Minh bạch giải thích**: Các đóng góp Log-odds được biểu diễn rõ ràng qua Linear Contributions/SHAP, không suy diễn quan hệ nhân quả tuyệt đối.\n"
                ]
            }
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python",
                "version": "3.13"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 2
    }

    out_file = Path("ml/notebooks/07_oulad_trained_model_analysis.ipynb")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(notebook, f, indent=1, ensure_ascii=False)
    print("Notebook written successfully to:", out_file.resolve())

if __name__ == "__main__":
    create_notebook()
