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

Data dianggap `VALID` jika:

- Google Maps menemukan data tempat.
- Nama/alamat kandidat mengandung `SPPG`, `Satuan Pelayanan Pemenuhan Gizi`, atau istilah sejenis.
- Nama kandidat cukup cocok dengan `Nama_SPPG`.
- Koordinat kandidat berada dalam ambang jarak dari `Longitude` dan `Latitude` CSV.
- Tempat tidak berada pada kondisi tanpa foto dan 0 review.

Default ambang jarak adalah 500 meter dan ambang kecocokan nama adalah 0.55. Ubah bila perlu:

```powershell
python validate_sppg_gmaps.py --distance-threshold-m 750 --name-threshold 0.50
```

Jumlah kandidat dari daftar hasil Google Maps bisa diubah:

```powershell
python validate_sppg_gmaps.py --max-candidates 5
```

## Catatan

Google Maps bisa berubah tampilan, meminta consent, atau menampilkan CAPTCHA. Jalankan mode non-headless terlebih dahulu agar Anda bisa menyelesaikan consent/verifikasi manual di Chrome yang dibuka Selenium. Profil browser disimpan di folder `selenium_chrome_profile`, sehingga sesi berikutnya bisa lanjut lebih mulus.
