# Remnawave Block Monitor

Автономный Linux-сервис, который сравнивает доступность IP-адресов и доменов с российских и зарубежных узлов Check-Host и дополняет результат признаками из CheburCheck. Предназначен для инфраструктуры Bedolaga + Remnawave, но не зависит от их контейнеров или API.

> Вердикты сервиса — технические эвристики, а не юридическое или абсолютное доказательство блокировки. Формулировка `CONFIRMED_BY_MULTIPLE_SIGNALS` означает совпадение независимых сигналов.

## Возможности

- TCP и HTTP(S) через официальный JSON API Check-Host, без HTML scraping;
- актуальный список узлов и выбор по country code, либо ручной список;
- CheburCheck API `/api/v1/check` с `blocked`, `rkn_domain`, `blocked_subnets`, `ips`, `cdn_providers`;
- состояния `OK`, `WARNING`, `LIKELY_RU_BLOCK`, `CONFIRMED_BY_MULTIPLE_SIGNALS`, `GLOBAL_DOWN`, `CHECK_ERROR`, `UNKNOWN`;
- debounce и атомарный state, переживающий рестарт;
- Telegram `sendMessage` без `getUpdates`, поэтому токен существующего бота не конфликтует с polling Bedolaga;
- ограничение параллельности, rate limit delay, `Retry-After`, повторы 429/5xx/DNS/timeout;
- непривилегированный systemd service с hardening;
- расширяемый `TargetProvider` и заготовка `RemnawaveTargetProvider` без выдуманного API-контракта.

Требования: Linux с systemd и Python 3.10+. Installer поддерживает Debian/Ubuntu, RHEL/CentOS/Rocky/Alma/Fedora, openSUSE/SLES и Arch/Manjaro.

## Быстрая установка

```bash
curl -fsSL https://raw.githubusercontent.com/VoskovschukDM/remnawave-block-monitor/main/install.sh | sudo bash
```

Для установки форка можно явно передать другой репозиторий:

```bash
curl -fsSL https://raw.githubusercontent.com/VoskovschukDM/remnawave-block-monitor/main/install.sh \
  | sudo REMNAWAVE_MONITOR_REPOSITORY=owner/repository bash
```

Установка из clone:

```bash
git clone https://github.com/VoskovschukDM/remnawave-block-monitor.git
cd remnawave-block-monitor
sudo ./install.sh
```

Повторный запуск выполняет update/repair. Файлы `/etc/remnawave-block-monitor/config.env` и `/etc/remnawave-block-monitor/targets.txt`, а также state не перезаписываются.

## Добавление целей

```bash
sudo nano /etc/remnawave-block-monitor/targets.txt
```

Формат:

```text
# name | target | type
Germany-01 | 94.156.237.252:443 | tcp
Netherlands-01 | node1.example.com:443 | tcp
Subscription | https://sub.example.com | http
Panel | https://panel.example.com | http
```

Поддержан и простой формат:

```text
1.2.3.4
node.example.com
https://sub.example.com
```

Пустые строки и строки с `#` игнорируются. Некорректная строка пропускается с предупреждением и номером строки. IP или явно заданный `tcp` проверяется по TCP. URL проверяется по HTTP(S). Для домена без типа действует `DOMAIN_CHECK_MODE=tcp,http`; один и тот же Check-Host node считается успешным, только если успешны все включённые режимы.

Query string URL передаётся внешней проверке, но заменяется на `<redacted>` в journald и Telegram, поскольку может содержать subscription token. URL с `user:password@host` отклоняется.

После изменения:

```bash
sudo systemctl restart remnawave-block-monitor
```

## Настройка Telegram

```bash
sudo nano /etc/remnawave-block-monitor/config.env
```

Укажите:

```ini
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456:token
TELEGRAM_CHAT_ID=123456789
```

Проверка без запуска daemon loop:

```bash
sudo -u remnawave-monitor remnawave-block-monitor --test-telegram
```

Токен и chat ID не выводятся в log/config summary. Telegram URL с токеном не включается в сообщения об ошибках.

## Эксплуатация

Статус:

```bash
systemctl status remnawave-block-monitor --no-pager
```

Логи:

```bash
journalctl -u remnawave-block-monitor -f
```

Один полный цикл:

```bash
sudo -u remnawave-monitor remnawave-block-monitor --once
```

Одна цель:

```bash
sudo -u remnawave-monitor remnawave-block-monitor --target 94.156.237.252:443
```

Явные пути полезны при запуске из clone:

```bash
python3 monitor.py --config ./config.env.example \
  --targets-file ./targets.txt.example --state-file ./state.json --once
```

## Логика вердиктов

| Check-Host RU | Check-Host control | CheburCheck | Verdict |
|---|---|---|---|
| все OK | все OK | clear | `OK` |
| все FAIL | есть OK | clear/unavailable | `LIKELY_RU_BLOCK` |
| все FAIL | есть OK | blocked | `CONFIRMED_BY_MULTIPLE_SIGNALS` |
| все FAIL | все FAIL | любой | `GLOBAL_DOWN` |
| частичный/асимметричный сбой | любой | любой | `WARNING` |
| Check-Host unavailable | — | blocked | `WARNING` |
| оба источника unavailable | — | — | `CHECK_ERROR` |

Отсутствующий результат Check-Host (`null`, проверка ещё идёт) не считается сетевым timeout цели. Клиент опрашивает отчёт до `CHECKHOST_RESULT_TIMEOUT`; незавершённые nodes исключаются из сравнения и помечаются API-ошибкой. Это защищает от ложного `RU block` при медленной генерации отчёта.

HTTP-ответ с любым валидным status code 100–599 считается доказательством HTTP-доступности: например, `404` говорит, что сервер ответил, даже если Check-Host помечает страницу как неуспешную.

## Debounce и уведомления

По умолчанию alert уходит после трёх подряд вердиктов `LIKELY_RU_BLOCK`, `CONFIRMED_BY_MULTIPLE_SIGNALS` или `GLOBAL_DOWN`. Recovery — после двух подряд `OK`. `WARNING`, `UNKNOWN` и `CHECK_ERROR` не доказывают восстановление. Одинаковый активный alert повторно не отправляется; изменение типа активной аварии отправляет обновление.

State: `/var/lib/remnawave-block-monitor/state.json`. Запись выполняется во временный файл, затем `fsync` + atomic `rename` + directory `fsync`. Повреждённый JSON переименовывается в `state.json.corrupt`, мониторинг продолжает работу с чистым state. При ошибке Telegram доставка будет повторена на следующем цикле.

## Конфигурация

Полный пример находится в `config.env.example`. Основные параметры:

```ini
CHECK_INTERVAL_SECONDS=600
CHECK_JITTER_SECONDS=30
MAX_CONCURRENT_TARGETS=3
DEFAULT_PORT=443
DOMAIN_CHECK_MODE=tcp,http

FAILURES_BEFORE_ALERT=3
RECOVERIES_BEFORE_ALERT=2

CHECKHOST_RU_COUNTRIES=RU
CHECKHOST_CONTROL_COUNTRIES=DE,NL,FI,PL
CHECKHOST_RU_NODE_COUNT=3
CHECKHOST_CONTROL_NODE_COUNT=3
CHECKHOST_RU_NODES=
CHECKHOST_CONTROL_NODES=

CHEBURCHECK_REQUEST_DELAY=2.2
HTTP_RETRY_ATTEMPTS=3
```

Если заполнены `CHECKHOST_RU_NODES` или `CHECKHOST_CONTROL_NODES`, соответствующая группа использует ручной список. Автовыбор распределяет контрольные узлы round-robin по указанным странам, чтобы не взять все три из одной страны.

## Отказ внешнего API

Источники независимы. При недоступности CheburCheck сравнение RU/control продолжает выдавать `LIKELY_RU_BLOCK` или `GLOBAL_DOWN`. Если недоступен Check-Host, один лишь list-based сигнал CheburCheck даёт `WARNING`, а не подтверждённую блокировку. 429 учитывает `Retry-After` (число секунд или HTTP-date, максимум 300 секунд); 5xx, timeout и DNS ошибки повторяются с backoff.

## Update и удаление

Update/repair — повторная установка:

```bash
curl -fsSL https://raw.githubusercontent.com/VoskovschukDM/remnawave-block-monitor/main/install.sh | sudo bash
```

Удалить приложение, сохранив config и state:

```bash
sudo ./uninstall.sh
```

Удалить всё безвозвратно:

```bash
sudo ./uninstall.sh --purge
```

## Разработка и тесты

Зависимости runtime отсутствуют — используется Python stdlib.

```bash
python3 -m compileall -q remnawave_block_monitor monitor.py tests
python3 -m unittest discover -s tests -v
bash -n install.sh uninstall.sh
systemd-analyze verify systemd/remnawave-block-monitor.service
```

CI выполняет эти проверки на Python 3.10, 3.12 и 3.13.

## API-источники

- [официальная документация Check-Host API](https://check-host.net/about/api);
- [исходный код CheburCheck](https://github.com/LowderPlay/cheburcheck), включая route `website/src/api/check.rs` и контракт frontend `frontend/src/lib/api/check.ts`.

API проверены при подготовке версии 1.0.0 (2026-08-25). Внешние сервисы могут менять контракт или лимиты независимо от этого проекта.

## Безопасность

Сервис работает как `remnawave-monitor`, не имеет Linux capabilities, видит `/opt` и `/etc` только для чтения и может писать только в `/var/lib/remnawave-block-monitor` и `/var/log/remnawave-block-monitor`. Секрет Telegram хранится в root-owned `config.env` с mode `0640`.

Не принимайте pull request, который начинает логировать весь config, Telegram request URL или тела внешних ошибок: в них могут оказаться секреты/операционные данные.

## License

MIT.

