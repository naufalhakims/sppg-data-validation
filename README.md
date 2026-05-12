# Validasi Data SPPG via Google Maps

Automation ini membaca CSV SPPG, membuka Google Maps dengan Selenium, mengambil data tempat, lalu membuat CSV baru dengan kolom validasi.

## Kolom hasil

- `Status`: `VALID` atau `TIDAK VALID`
- `GMaps_Nama`
- `GMaps_Alamat`
- `GMaps_Longitude`
- `GMaps_Latitude`
- `GMaps_Rating`
- `GMaps_Reviews`
- `GMaps_Foto`
- `GMaps_Foto_URL`
- `GMaps_Photo_File`
- `GMaps_Photo_Save_Error`
- `GMaps_Distance_Meter`
- `GMaps_Name_Score`
- `GMaps_Source`
- `GMaps_Query`
- `GMaps_Candidate_Count`
- `GMaps_Filtered_Candidate_Count`
- `GMaps_Is_SPPG_Like`
- `GMaps_Error`

## Instalasi

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Pastikan Google Chrome sudah terpasang. Selenium 4 akan memakai Selenium Manager untuk mencari atau mengunduh ChromeDriver yang sesuai.

## Cara menjalankan

Tes 5 baris dulu:

```powershell
python validate_sppg_gmaps.py --input "sppg_jawa_timur (1).csv" --limit 5
```

Jalankan semua data:

```powershell
python validate_sppg_gmaps.py --input "sppg_jawa_timur (1).csv" --output "outputs\sppg_jawa_timur_validated.csv"
```

Secara default foto akan disimpan ke folder dengan nama mengikuti output CSV, misalnya:

```text
outputs\sppg_jawa_timur_validated_photos
```

Anda juga bisa menentukan folder foto sendiri:

```powershell
python validate_sppg_gmaps.py --input "sppg_jawa_timur (1).csv" --output "outputs\sppg_jawa_timur_validated.csv" --photo-dir "outputs\photos_sppg"
```

Lanjutkan proses yang terputus:

```powershell
python validate_sppg_gmaps.py --input "sppg_jawa_timur (1).csv" --output "outputs\sppg_jawa_timur_validated.csv" --resume
```

Gunakan `--resume` hanya untuk file output yang dibuat dengan versi kolom yang sama. Jika kode baru menambah kolom, buat file output baru.

## Logika validasi

Flow validasi:

1. Search Google Maps memakai `Nama_SPPG`.
2. Jika Google Maps langsung membuka satu tempat, ambil detail tempat tersebut.
3. Jika Google Maps menampilkan daftar hasil, ambil maksimal 3 hasil teratas.
4. Pada mode daftar hasil, filter kandidat terlebih dahulu. Kandidat harus mengandung `SPPG`, `Satuan Pelayanan Pemenuhan Gizi`, atau istilah sejenis seperti `MBG`.
5. Pilih kandidat hasil filter dengan kemiripan nama terbaik memakai gabungan token matching, `SequenceMatcher`, dan Levenshtein distance.
6. Bandingkan koordinat kandidat Google Maps dengan `Longitude` dan `Latitude` dari CSV.

Data dianggap `VALID` jika dan hanya jika semua syarat ini terpenuhi:

- Google Maps menemukan data tempat.
- Nama/alamat kandidat mengandung `SPPG`, `Satuan Pelayanan Pemenuhan Gizi`, atau istilah sejenis.
- Nama kandidat cukup cocok dengan `Nama_SPPG`.
- Foto Google Maps terdeteksi.
- Koordinat kandidat berada dalam ambang jarak 500 meter dari `Longitude` dan `Latitude` CSV.

Jika salah satu syarat hilang, `Status` menjadi `TIDAK VALID`. Rating dan review tetap diambil sebagai data pendukung, tetapi bukan syarat utama `VALID`.

Default ambang jarak adalah 500 meter dan ambang kecocokan nama adalah 0.55. Ubah bila perlu:

```powershell
python validate_sppg_gmaps.py --distance-threshold-m 750 --name-threshold 0.50
```

Jumlah kandidat dari daftar hasil Google Maps bisa diubah:

```powershell
python validate_sppg_gmaps.py --max-candidates 5
```

## Foto

Setiap baris output akan memiliki file di `GMaps_Photo_File`.

- Jika foto Google Maps ada, skrip mencoba mengunduh foto tersebut sebagai `.jpg`.
- Jika foto tidak ada, skrip membuat file blank `.png`.
- Jika foto ada tetapi gagal diunduh, skrip tetap membuat file blank `.png` dan mencatat penyebabnya di `GMaps_Photo_Save_Error`.

File foto dinamai dengan nomor baris dan nama SPPG, contohnya:

```text
00004_sppg_sidoarjo_waru_pepelegi.jpg
```

## Fallback dan Resume

Skrip menulis hasil per baris langsung ke CSV dan menyimpan foto per baris. Jika proses berhenti di tengah jalan karena CAPTCHA, koneksi, browser tertutup, atau error lain, jalankan ulang dengan `--resume` dan path `--output` yang sama:

```powershell
python validate_sppg_gmaps.py --input "sppg_jawa_timur (1).csv" --output "outputs\sppg_jawa_timur_validated.csv" --resume
```

Cara kerja `--resume`:

- Skrip menghitung jumlah baris yang sudah ada di CSV output.
- Baris sumber yang sudah memiliki output akan dilewati.
- Proses dilanjutkan dari baris berikutnya.
- Folder foto default tetap sama karena diturunkan dari nama output CSV.
- Jika memakai `--photo-dir` custom saat run pertama, pakai `--photo-dir` yang sama saat resume.

Contoh resume dengan folder foto custom:

```powershell
python validate_sppg_gmaps.py --input "sppg_jawa_timur (1).csv" --output "outputs\sppg_jawa_timur_validated.csv" --photo-dir "outputs\photos_sppg" --resume
```

Jangan memakai `--resume` untuk file output dari versi kode lama yang kolomnya berbeda. Skrip akan berhenti jika mendeteksi kolom output lama tidak kompatibel.

## Catatan

Google Maps bisa berubah tampilan, meminta consent, atau menampilkan CAPTCHA. Jalankan mode non-headless terlebih dahulu agar Anda bisa menyelesaikan consent/verifikasi manual di Chrome yang dibuka Selenium. Profil browser disimpan di folder `selenium_chrome_profile`, sehingga sesi berikutnya bisa lanjut lebih mulus.
