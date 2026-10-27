# Shorts Factory

Мультиканальная фабрика коротких видео: discovery → нарезка → субтитры → метаданные → публикация,
с поддержкой **шахматного контента**, **оригинальных stock-шортов** и **affiliate-монетизации**.

> ## ⚠️ Основано на открытом проекте
>
> Основа — **[`random-or/shorts-clipper`](https://github.com/random-or/shorts-clipper)** автора
> [Abhishek Rai](https://github.com/random-or) (MIT, © Shorts Clipper contributors). Это не GitHub-форк,
> а самостоятельная публикация: апстрим был взят как движок нарезки и расширен. Сохранён без изменений
> ядровый пайплайн: discovery, editorial engine с 8 judges, транскрипция faster-whisper,
> рендер FFmpeg, публикация в YouTube/Instagram.
>
> **Всё, что ниже в разделе «Что я добавил» — моя работа: 159 файлов, ~39 400 строк, включая 75 файлов тестов.**
> Полный разбор «моё / унаследованное» — в [`docs/FORK.md`](docs/FORK.md).
>
> Лицензия MIT обязывает сохранять оригинальный копирайт — он в `LICENSE` не тронут.

---

## Зачем это

Я использовал апстрим как движок нарезки и построил поверх него **фабрику контента** — то, чего в апстриме нет:

1. **Шахматная федерация.** Автоматический выпуск Shorts/Reels с разборами партий. Для разбора партии
   не нужен ни войсовер, ни чужое видео — визуалом служит сама доска. Полностью лицензионно чисто и детерминированно.
2. **Оригинальный контент без чужого видео.** Stock-режим собирает шорт из цитаты + локального фона +
   Ken-Burns + локального TTS. Ноль VOD, ноль API-ключей, ноль copyright-риска.
3. **Мультиканальность и монетизация.** Ниши, ротация каналов, affiliate-офферы, отчёты по удержанию и доходам.

---

## Что я добавил

| Модуль | Файлов | Строк | Что делает |
|---|---|---|---|
| `shorts_clipper/chess/` | 11 | 6 606 | PGN → решающий ход → отрисовка позиции → нарезка с музыкой. 3 формата: решающий ход, теория дебюта, эндшпиль. Дедуп по «позиция + ход» |
| `shorts_clipper/visual/` | 3 | 1 477 | Ken-Burns zoompan по локальным MP4, теги из имени файла / папки / sidecar |
| `shorts_clipper/audio/` | 4 | 2 001 | Локальный Piper TTS, музыкальные подложки, абстракция TTS |
| `shorts_clipper/attention/` | 4 | 1 002 | Judges: gameplay, emotion, audio energy, stream |
| `shorts_clipper/compliance/` | 3 | 454 | Compliance gate: правила + опциональный LLM-ревью |
| `shorts_clipper/pipeline/` | 2 | 904 | `stock_runner.py` (сборка stock-шорта), `stock_dedup.py` (дедуп по хэшу сценария) |
| `shorts_clipper/captions/music.py` | 1 | 427 | Выбор BGM + фолбэк на Jamendo / синтез |
| `shorts_clipper/cli/` | 3 | 712 | `doctor`, `retention-report`, `revenue-report` |
| `shorts_clipper/publishers/tiktok/` | 1 | — | TikTok Content Posting API (Direct Post) |
| `shorts_clipper/core/` | 6 | — | Планировщик публикаций (JSON-очередь), metrics store, кэш загрузок, processed store, cleanup |
| `shorts_clipper/scout/` | 4 | — | Расширения discovery: trends, channel VODs, auto_batch, source_scout |
| `scripts/` | 13 | 2 137 | `factory.py` (autopilot-цикл, дневной кап, расписание), `multi_channel.py`, `collect_metrics.py`, `report.py`, `make_chess_clip.py`, `make_phonk.py`, `make_dark_industrial.py`, `fetch_music.py`, `fetch_studies.py`, `run_clips.py`, `smoke_test.py` |
| `deploy/` | 5 | 153 | systemd service + timer, `install.sh` для чистого VPS, таймер метрик |
| `.github/workflows/factory.yml` | 1 | 88 | Ежедневный cron-запуск фабрики |
| `data/niches/`, `config/` | 10 | 417 | Сценарии ниш, Pexels-запросы, конфиг партнёрок |
| `tests/` | 75 | 18 493 | Новые тесты (было 15 → стало 90) |

---

## Шахматный модуль

```
PGN → найти решающий ход → отрисовать позицию → нарезать с музыкой
```

```bash
pip install -e ".[chess]"        # python-chess + Pillow
shorts-clipper chess data/pgns/ --count 5
```

- `--count` — бюджет на весь запуск: сначала анализируются все партии, потом режутся лучшие N моментов
  по всей библиотеке
- Дедуп по «позиция + ход»: один и тот же зевок не будет нарезан повторно
- Клип — три бита: позиция **до** хода, ход со стрелкой, позиция **после**.
  Без состояния «до» зритель видит, что что-то произошло, но не видит, что это было ошибкой

**Оценка честная по конструкции.** Stockfish скачивается по требованию в `models/stockfish/` (98 МБ,
проверка sha256 против digest релиза). Приоритет: `SHORTS_CHESS_ENGINE` → бинарь в `PATH` → кэш.
**Без движка работает фолбэк на оценку материала, и каждый такой результат помечается `Decision.material = True`**,
чтобы оценка не выдавалась за анализ.

Фолбэк действительно слабее, и это проверено: на дебюте «Бессмертной партии» он помечает три
*жертвы* Андерсена (`g4` 360cp, `Nf5` 295cp, `Bxf4` 225cp) как потери, а Stockfish — ни одной.

### Тактические задачи

Отдельный формат для привлечения аудитории в клуб — короткие задачи из курируемой базы Lichess:

```bash
shorts-clipper chess --format tactic --count 5
```

- Источник — **Lichess puzzle DB** (~300 МБ, скачивается один раз). Каждая задача решена и оценена
  тысячами людей, поэтому фабрика не режет скучные «стокфишные» позиции.
- Фильтр качества: рейтинг 1400–2000, популярность ≥ 85, ≥ 2000 решений, только интересные мотивы
  (вилка, связка, жертва, тихий ход, мат в 2–3 и др.), исключены «мат в 1» и «просто съесть фигуру».
- Клип: позиция → голос «Найдёшь здесь тактику?» → пауза 5 секунд → ответ со стрелкой и мотивом →
  CTA «Вступай в клуб» с ссылкой в описании.
- Рядом с видео создаётся `.txt` с title, description, ссылками на клуб и хештегами.
- Использованные задачи сохраняются в `data/puzzles/selected.used.json`, чтобы не повторяться.

### Разборы реальных партий

```bash
shorts-clipper chess --format tournament https://lichess.org/tournament/MwiQDf4S --count 3
```

- Берёт партии из турнира Lichess, находит в каждой решающий зевок и рендерит разбор.
- Голос: «Белые на ходу. Здесь решилась партия…» → ответ с оценкой → CTA.
- Автоматические title/description с ссылками на клуб.
- Дедупликация через `data/chess_used.json`.

### Клубные челленджи

```bash
shorts-clipper chess --format club-challenge https://lichess.org/tournament/MwiQDf4S --count 3
```

- Ищет в партиях турнира позиции с одним явно лучшим ходом.
- Фильтрует по рейтингу игроков, предпочитает сильных членов клуба.
- Формат: «Сможешь сыграть как 2000? Найди ход!» → ответ → CTA.

### Истории клуба

```bash
# Рекап турнира
shorts-clipper chess --format story https://lichess.org/tournament/MwiQDf4S --count 1

# Кастомная история
shorts-clipper chess --format story data/stories/member_week_1.json --story-template member
```

- Автоматически собирает рекап турнира: название, дата, пьедестал, статистика.
- Поддерживает кастомные JSON-сценарии для «участник недели», «закулисье» и т.д.
- Placeholder аватара в `assets/presenter/placeholder.png` — замените на фото/видео ведущего.

---

## Stock-режим (оригинальные шорты)

Вместо нарезки чужого VOD фабрика собирает **оригинальный** шорт: сценарий (цитата/философия),
фон (локальный MP4 или процедурный градиент), медленный Ken-Burns, пословные субтитры, TTS-войсовер.

```bash
mkdir -p data/stock/self-growth        # опционально: $NICHE/файл.mp4
SHORTS_VISUAL_MODE=stock \
SHORTS_STOCK_DIR=data/stock \
shorts-clipper autopilot --niche self-growth --count 5
```

- `SHORTS_VISUAL_MODE`: `clip` (по умолчанию) или `stock`
- `SHORTS_STOCK_DIR`: папка с фонами; подпапка `data/stock/<niche>/` перекрывает общий пул для ниши
- `SHORTS_STOCK_SCRIPT_PATH`: опциональный файл, одна строка = один шорт; без него — встроенный банк цитат
  (seeded, стабилен между запусками)
- Голос подбирается по языку сценария (RU → `ru-RU-DmitryNeural`)

**Подбор «сценарий ↔ фон».** Цитата выбирается *после* фона, из сценариев, чей смысл подходит клипу —
строка про 23:00 больше не ложится на рассвет в лесу. Теги берутся из имени файла и папки
(`city_night_rain.mp4` → `city`, `city_night`, `night`, `rain`); можно переопределить sidecar-файлом
`<clip>.tags.txt` или `<clip>.json`. В одном батче сценарий не повторяется, как и почти-дубликат клипа.

---

## Фабрика (мультиканальность)

```bash
python scripts/multi_channel.py                            # канал по умолчанию
python scripts/multi_channel.py --channels alpha,bravo     # несколько каналов
python scripts/multi_channel.py --channels alpha --limit 0 # dry-run
python scripts/factory.py --loop-interval 60 --schedule-interval-min 90 --daily-cap 6
```

Деплой (systemd timers, Docker, GitHub Actions cron + state-артефакты) — в [`DEPLOY.md`](DEPLOY.md).

---

## Отчёт по удержанию (decision science)

```bash
shorts-clipper retention-report --platform youtube --days 30 --niche self-growth
```

Читает metrics store и агрегирует каждый выпущенный клип по `(platform, niche)` в детерминированный
JSON + Markdown отчёт:

- счётчики: `clips`, `published`, `publish_rate`
- медианы просмотров/лайков/комментариев
- `avg_hook_score` / `avg_energy`, если колонки есть (старые схемы отдают `not_available`, а не падают)
- **`retention_grade` A/B/C/D**: `engagement = median(likes+comments)/median(views)`,
  `retention_score = publish_rate × engagement`, пороги `A ≥ 0.75`, `B ≥ 0.50`, `C ≥ 0.25`.
  Формула вшита в JSON-блок `schema`, чтобы отчёт можно было воспроизвести

---

## Compliance gate

Правила + опциональный LLM-ревью. **Гейт никогда не роняет пайплайн:** любая неожиданная ошибка
деградирует в `level="review"`, и публикация продолжается с предупреждением.

---

## Батч-запуски

```bash
shorts-clipper clip --source URL1 URL2 URL3
shorts-clipper autopilot --batch-file sources.txt
shorts-clipper autopilot --source URL1 --continue-on-error
```

Источники обрабатываются последовательно; каждый успешный клип пишется в metrics store.
По умолчанию батч **fails fast** — первый сбой логирует понятную строку `[source N] <url> FAILED: ...`,
прерывает остальные и завершается с ненулевым кодом. `--continue-on-error` продолжает, но код всё равно ненулевой,
если что-то упало — жёсткий сбой никогда не проглатывается молча.

---

## Тесты

```bash
python -m pytest tests/ -q
ruff check . && ruff format --check .
```

90 файлов тестов (75 добавлено поверх 15 из апстрима). Покрыты chess (18 файлов), compliance (5),
stock (8), music (5), affiliate (3), metrics, retention, scheduling, scout, multilingual, layout.

---

## Лицензия

MIT. Оригинальный копирайт «Shorts Clipper contributors» в `LICENSE` сохранён, как требует лицензия.
