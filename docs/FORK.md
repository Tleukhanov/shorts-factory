# Что моё, что унаследовано

Этот репозиторий — **не GitHub-форк**, а самостоятельная публикация на основе открытого проекта
[`random-or/shorts-clipper`](https://github.com/random-or/shorts-clipper) автора
[Abhishek Rai](https://github.com/random-or) (MIT, © Shorts Clipper contributors).

Раньше репозиторий назывался `chess_auto_zavod_ai` — это имя не отражало содержимое и не сообщало
об источнике. Переименован, источник раскрыт здесь и в `README.md`.

Оригинальный копирайт в `LICENSE` не тронут — это требование MIT, и оно выполнено.

Метод сравнения: скачивание архивов апстрима и этого репозитория, побайтовое сравнение 286 файлов.

## Итог

| | Файлов | Строк |
|---|---|---|
| **Мои добавления** | **159** | **39 404** |
| Унаследовано из апстрима (без изменений) | 127 | — |
| Удалено из апстрима | 32 | — |
| Тестов: было 15 → стало | 90 | — |

Из моих 159 файлов **75 — тесты (18 493 строки)**.

## Мои модули

| Модуль | Файлов | Строк | Что делает |
|---|---|---|---|
| `shorts_clipper/chess/` | 11 | 6 606 | PGN → поиск решающего хода → отрисовка позиции → нарезка с музыкой. Stockfish скачивается с sha256-проверкой; без движка — фолбэк на оценку материала, и **каждый такой результат помечается `Decision.material = True`**, чтобы оценка не выдавалась за анализ. 3 формата: решающий ход, теория дебюта, эндшпиль. Дедуп по «позиция + ход» |
| `shorts_clipper/visual/` | 3 | 1 477 | Stock-режим: Ken-Burns zoompan по локальным MP4, теги из имени файла / папки / sidecar |
| `shorts_clipper/audio/` | 4 | 2 001 | Локальный Piper TTS, музыкальные подложки (dark industrial, phonk), абстракция TTS |
| `shorts_clipper/attention/` | 4 | 1 002 | Дополнительные judges: gameplay, emotion, audio energy, stream |
| `shorts_clipper/compliance/` | 3 | 454 | Compliance gate: правила + опциональный LLM-ревью. **Никогда не роняет пайплайн** — любая ошибка деградирует в `level="review"` |
| `shorts_clipper/pipeline/` | 2 | 904 | `stock_runner.py` (сборка stock-шорта), `stock_dedup.py` (дедуп по хэшу сценария) |
| `shorts_clipper/captions/music.py` | 1 | 427 | Выбор BGM + фолбэк на Jamendo / синтез |
| `shorts_clipper/cli/` | 3 | 712 | `doctor`, `retention-report`, `revenue-report` |
| `shorts_clipper/publishers/tiktok/` | 1 | — | Публикация через TikTok Content Posting API (Direct Post) |
| `shorts_clipper/core/` | 6 | — | Планировщик публикаций (JSON-очередь на диске), metrics store, кэш загрузок, processed store, cleanup |
| `shorts_clipper/scout/` | 4 | — | Расширения discovery: trends, channel VODs, auto_batch, source_scout |
| `scripts/` | 13 | 2 137 | `factory.py` (autopilot-цикл, дневной кап, расписание), `multi_channel.py`, `collect_metrics.py`, `report.py`, `make_chess_clip.py`, `make_phonk.py`, `make_dark_industrial.py`, `fetch_music.py`, `fetch_studies.py`, `run_clips.py`, `smoke_test.py` |
| `deploy/` | 5 | 153 | systemd service + timer, `install.sh` для чистого VPS, таймер метрик |
| `.github/workflows/factory.yml` | 1 | 88 | Ежедневный cron-запуск фабрики |
| `data/niches/`, `config/` | 10 | 417 | Сценарии ниш (money / philosophy / relationships / self-growth), Pexels-запросы, конфиг партнёрок |
| `tests/` | 75 | 18 493 | Новые тесты (chess×18, compliance×5, stock×8, music×5, affiliate×3, metrics, retention, scheduling, scout, multilingual, layout…) |

Плюс отдельные файлы: `DEPLOY.md`, `affiliate_partners.example.json`,
`core/{metrics,processed_store,scheduler,scheduling,cleanup,download_cache}.py`,
`downloader/music_scraper.py`, `editorial/retention_amplify.py`, `highlight_detection/hook_judge.py`,
`inspect.py`, `rendering/render_effects.py`, `utils/ffmpeg_path.py`.

## Унаследовано из апстрима (не моё)

Ядро нарезки: `analyze`, `api`, `captions` (базовые), `core` (базовые), `cropping`, `downloader` (базовые),
`editorial` (движок + 8 judges), `highlight_detection`, `metadata`, `pipeline` (базовый), `providers`,
`publishers/{youtube,instagram}`, `rendering` (базовые), `scout` (базовые), `transcription`, `ui`, `utils`.

Плюс: `README.md` (переписан), `ARCHITECTURE.md`, `CONSTITUTION.md`, `CONTRIBUTING.md`, `SECURITY.md`,
`CHANGELOG.md`, `LICENSE`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml` (базовый), `tests/` (15 файлов).

## Зачем это было

- **Шахматная федерация** → автоматический выпуск Shorts/Reels с разборами партий (модуль `chess/`):
  без войсовера, без чужого видео — доска и есть визуал. Лицензионно чисто и детерминированно
- **Оригинальный контент** → stock-режим: цитата + локальный фон + Ken-Burns + TTS.
  Ноль VOD, ноль API-ключей, ноль copyright-риска
- **Мультиканальность** → `multi_channel.py` + ниши + конфиг партнёрок → монетизация через affiliate
