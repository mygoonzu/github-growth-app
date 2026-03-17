# GitHub Weekly Growth Repos

CLI Python de tim cac repository public tren GitHub co:
- Tong stars >= nguong (mac dinh `500`)
- Tang truong star nhanh theo tuan

## Tinh nang
- Lay danh sach repo public theo nguong stars
- Tinh `weekly_stars`, `previous_week_stars`, `delta`, `growth_rate`
- Sap xep theo `delta`, `weekly_stars` hoac `growth_rate`
- Ho tro output bang text hoac JSON
- Co retry/backoff cho loi API tam thoi

## Yeu cau
- Python 3.9+
- GitHub token (read-only la du)

## Tao token GitHub (an toan)
1. Vao `https://github.com/settings/tokens`
2. Tao token moi (fine-grained)
3. Chon quyen toi thieu de doc du lieu public
4. Copy token va luu o local (khong commit vao repo)

## Cai dat
```bash
git clone https://github.com/<username>/<repo-name>.git
cd <repo-name>
```

Tao file `.env` tu mau:
```bash
cp .env.example .env
# mo .env va dien token that
```

Hoac set truc tiep bien moi truong:
```bash
export GITHUB_TOKEN="<your_token>"
```

## Chay nhanh
```bash
python3 github_growth_app.py
```

## Vi du su dung
Top 20 repo co stars >= 500, toi da 50 repo de phan tich:
```bash
python3 github_growth_app.py \
  --min-stars 500 \
  --max-repos 50 \
  --min-weekly-stars 1 \
  --sort-by delta \
  --top 20
```

Xuat JSON:
```bash
python3 github_growth_app.py --json --top 20 > result.json
```

## Tham so
- `--token`: GitHub token (neu khong truyen se doc tu `GITHUB_TOKEN` hoac `.env`)
- `--min-stars`: nguong tong stars toi thieu (mac dinh `500`)
- `--max-repos`: so repo toi da can phan tich (mac dinh `30`)
- `--min-weekly-stars`: nguong stars toi thieu trong 7 ngay (mac dinh `20`)
- `--sort-by`: tieu chi sap xep (`delta`, `weekly_stars`, `growth_rate`)
- `--top`: so ket qua hien thi (mac dinh `15`)
- `--max-star-pages`: so trang stargazers toi da moi repo, 100 records/trang (mac dinh `20`)
- `--json`: in ket qua JSON

## Cach tinh
- `weekly_stars`: so star trong 7 ngay gan nhat
- `previous_week_stars`: so star 7 ngay truoc do
- `delta = weekly_stars - previous_week_stars`
- `growth_rate = weekly_stars / previous_week_stars` (`inf` neu mau so = 0)

## Bao mat
- Khong paste token vao code/README
- Khong commit file `.env`
- Neu nghi token lo, revoke ngay trong GitHub settings

## Troubleshooting
- `Thieu GitHub token`: set `GITHUB_TOKEN` hoac tao `.env`
- `Khong co repo nao khop dieu kien`: giam `--min-weekly-stars` (vd `0` hoac `1`)
- API loi tam thoi: chay lai, script da co retry
