import os
import uuid
import tempfile
import ffmpeg
import pickle
from flask import Flask, request, redirect, url_for, send_file, render_template, flash
from werkzeug.utils import secure_filename
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)
app.secret_key = 'secret_key_thay_doi_de_bao_mat'  # Thay đổi key này cho phù hợp

ALLOWED_EXTENSIONS = {'mts'}

# Dictionary lưu mapping token -> file path (cho file chuyển đổi)
converted_files = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def convert_mts_to_mp4(input_filepath, output_filepath):
    """
    Chuyển đổi file MTS sang MP4 sử dụng ffmpeg.
    """
    try:
        (
            ffmpeg
            .input(input_filepath)
            .output(output_filepath, vcodec='libx264', acodec='aac')
            .run(overwrite_output=True)
        )
        return True
    except ffmpeg.Error as e:
        print("Lỗi trong quá trình chuyển đổi:", e)
        return False

def upload_to_google_drive(file_path, folder_id=None):
    """
    Tải file lên Google Drive và trả về file ID.
    """
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        from google.auth.transport.requests import Request
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    service = build('drive', 'v3', credentials=creds)

    file_metadata = {'name': os.path.basename(file_path)}
    if folder_id:
        file_metadata['parents'] = [folder_id]

    media = MediaFileUpload(file_path, mimetype='video/mp4')
    uploaded_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return uploaded_file.get('id')

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Không tìm thấy file trong yêu cầu')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Không có file nào được chọn')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            # Lưu file upload vào file tạm (.mts)
            filename = secure_filename(file.filename)
            with tempfile.NamedTemporaryFile(suffix='.mts', delete=False) as temp_input:
                file.save(temp_input)
                input_filepath = temp_input.name

            # Tạo file tạm cho file chuyển đổi (.mp4)
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_output:
                output_filepath = temp_output.name

            # Chuyển đổi file bằng ffmpeg
            if not convert_mts_to_mp4(input_filepath, output_filepath):
                flash("Chuyển đổi thất bại")
                os.remove(input_filepath)
                os.remove(output_filepath)
                return redirect(request.url)

            # Tải file đã chuyển đổi lên Google Drive (điền folder_id nếu cần)
            folder_id = "1jb74DthhcM1ZxgNT1hDTnAqa0kBYs4b4"  # Thay đổi folder_id nếu cần, hoặc đặt None
            drive_file_id = upload_to_google_drive(output_filepath, folder_id=folder_id)
            drive_file_link = f"https://drive.google.com/file/d/{drive_file_id}/view?usp=sharing"

            # Tạo token duy nhất để download file từ server
            token = str(uuid.uuid4())
            converted_files[token] = output_filepath

            # Xóa file input tạm (không cần dùng nữa)
            os.remove(input_filepath)

            download_link = url_for('download_file', token=token)
            flash(
                f"Chuyển đổi và tải lên thành công!<br>"
                f"Link file trên Drive: <a href='{drive_file_link}' target='_blank'>Xem file trên Drive</a><br>"
                f"<a href='{download_link}' class='btn btn-primary'>Tải file về</a>"
            )
            return redirect(url_for('index'))
        else:
            flash("File không hợp lệ. Chỉ cho phép file có đuôi .mts")
            return redirect(request.url)
    return render_template('index.html')

@app.route('/download/<token>')
def download_file(token):
    """
    Gửi file đã chuyển đổi từ file tạm cho người dùng, sau đó xóa file.
    """
    if token not in converted_files:
        flash("File không tồn tại hoặc đã được tải về")
        return redirect(url_for('index'))

    file_path = converted_files.pop(token)
    if not os.path.exists(file_path):
        flash("File không tồn tại trên server")
        return redirect(url_for('index'))

    # Gửi file và xóa file sau khi gửi
    try:
        return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))
    finally:
        os.remove(file_path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=True)
