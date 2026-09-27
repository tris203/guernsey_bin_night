# Guernsey Bin Night

Home Assistant sensors for the States of Guernsey's [My Bin Night](https://www.gov.gg/mybinnight) service. Enter your postcode, choose your address, and use the collection dates in dashboards and automations. No account, API key, YAML, or internal address ID is needed.

## Installation

Requires Home Assistant **2026.2 or later**.

### HACS

Install from `tris203/guernsey_bin_night`:

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/tris203/guernsey_bin_night` with type **Integration**.
3. Find **Guernsey Bin Night** in HACS and download it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration → Guernsey Bin Night**.
6. Enter your full postcode and select your address from the dropdown.

This is a HACS custom repository; it is not yet listed in the default HACS catalog.

### Manual

Copy `custom_components/guernsey_bin_night` into your Home Assistant `config/custom_components/` directory, restart, and add the integration as above. If using the ZIP, extract it into your configuration directory so that `config/custom_components/guernsey_bin_night/manifest.json` exists.

## Sensors

Each address creates one device containing:

| Sensor | State | Attributes |
| --- | --- | --- |
| Next collection | Next date with any collection | `collections`: material names; `days_until`: whole days |
| Food | Next food date | `days_until`, `service_id` |
| Glass | Next glass date | `days_until`, `service_id` |
| Residual waste | Next general rubbish date | `days_until`, `service_id` |
| Paper and cardboard | Next paper/cardboard date | `days_until`, `service_id` |
| Cans, plastics, cartons | Next cans/plastics/cartons date | `days_until`, `service_id` |

Material names and available services come from the collection service. Additional services appear automatically if the collection service adds them. Each sensor has Home Assistant's native `date` device class, and IDs remain stable across restarts. Multiple addresses can be added; duplicate addresses are rejected.

The default device name is **Bin collections**, producing short names such as **Bin collections Food** and, on a new installation, `sensor.bin_collections_food`. The integration entry still shows the full address. For multiple properties, rename each device in Home Assistant (for example, **Home bins** and **Office bins**). Existing custom names and entity IDs are preserved; you can shorten old entity IDs in each entity's settings, updating any dashboard or automation references that use them.

Material sensors expose the collection service's image URL in Home Assistant's standard `entity_picture` attribute when supplied. Cards that support entity pictures can use it directly; templates can read it with `state_attr('sensor.bin_collections_food', 'entity_picture')`. The image URL is retained with the saved schedule. Images are loaded from the collection service's site when displayed, so rendering them requires connectivity. If no image is supplied, the sensor keeps its generic `icon` attribute. The overall next-collection sensor uses a bin icon because several materials may be due together.

Dates match the My Bin Night website exactly, with **no one-day offset**. Today's bin night remains current until midnight. Use Home Assistant's `Europe/Guernsey` time zone (Settings → System → General) so midnight and reminders follow local time, including daylight saving changes.

The integration fetches one schedule per address every **24 hours** by default: one scheduled request per address per day. Change this to 1–24 hours using the integration's **Configure** button. All sensors share that request. Midnight updates recalculate the existing schedule without making an extra request. Setup, restarts, and manual refreshes make additional requests. You can use Home Assistant's `homeassistant.update_entity` action to request a refresh.

If the collection service is unreachable or returns malformed data, sensors continue using the last successfully fetched schedule, including across Home Assistant restarts. Known dates still advance at midnight. Each sensor exposes `last_successful_update` (the time of the last successful API refresh) and `data_stale` (true after a failed refresh). Failed refreshes retry after **15 minutes, 30 minutes, 1 hour, 2 hours, 4 hours, then every 6 hours**. The retry delay never exceeds your configured interval. A successful response replaces the saved schedule, clears `data_stale`, and returns to the normal refresh interval. Restarting or reloading resets the retry sequence.

A successful response with no future dates uses normal polling: `unknown` alone is not a request failure and does not trigger faster retries. Without a saved schedule, Home Assistant handles initial setup retries.

When there is no future date left for a material, its sensor becomes `unknown`; dates are never extrapolated beyond the saved schedule. A successful empty schedule also replaces the old data. Without a saved schedule, initial setup retries automatically until the API is reachable. Saved data is removed when you delete the integration entry.

To change address, remove the old integration entry and add the new address. Sensor IDs belong to the address, so review any automations when moving house.

## Example reminder

Replace `sensor.your_address_next_collection` with the actual entity ID shown on your integration's device page, and replace the notification action with your phone's action. This sends a reminder at 18:00 on the date displayed by the collection service:

```yaml
alias: Guernsey bin night reminder
triggers:
  - trigger: time
    at: "18:00:00"
conditions:
  - condition: template
    value_template: >-
      {{ states('sensor.your_address_next_collection') == now().date().isoformat() }}
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "Bin night"
      message: >-
        Put out: {{ (state_attr('sensor.your_address_next_collection', 'collections') or []) | join(', ') }}.
mode: single
```

For the evening before the displayed date, change the condition to compare the sensor with `(now() + timedelta(days=1)).date().isoformat()`.

## Migrating from the original YAML

The existing `bin_collections.yaml` is a local reference and is not modified or included in the release package. It contains a personal address ID and is ignored by Git.

1. Install and configure this integration alongside the old YAML.
2. Compare the dates and update your automations/dashboard cards to use the new entity IDs. The next-collection sensor retains `collections` and `days_until` attributes; individual material dates are now separate sensors.
3. Remove the old REST sensor and corresponding template sensors from your Home Assistant configuration, then restart.

There is no automatic migration of unrelated REST/template entities or their entity IDs.

## Troubleshooting and data source

- **No addresses:** use a full postcode. Lowercase and omitted spaces are accepted. Check the [fallback site linked from gov.gg](https://guernsey.isl-fusion.com/) if your address is missing.
- **Connection error:** retry later. The integration calls the public Fusion API directly, so it does not depend on the gov.gg search proxy.
- **Unknown date:** the collection service has not supplied a future date for that material. Check the website; the integration does not invent a recurring schedule.
- **Stale data:** a refresh failed. Saved dates remain usable, but changes made by the collection service cannot be picked up until a refresh succeeds. Check `last_successful_update`, connectivity and the Home Assistant logs.
- **Missing integration after installation:** restart Home Assistant and confirm the directory structure and minimum version.

This is an independent community integration, not an official States of Guernsey product. It uses the public endpoints consumed by the collection service's site:

- `GET https://guernsey.isl-fusion.com/api/search/{postcode}`
- `GET https://guernsey.isl-fusion.com/api/address/{address_id}`

Your postcode is sent to that service during lookup, and the selected address ID is sent during refreshes. The selected address and postcode are stored in Home Assistant's configuration. The last successful schedule, including its address, is saved locally in Home Assistant's `.storage` directory for use during outages. The integration adds no analytics and does not log addresses or request URLs. The API is undocumented and may change.

## Development and packaging

```sh
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=custom_components.guernsey_bin_night --cov-report=term-missing
python3 scripts/package.py
```

Tests run against Home Assistant 2026.2.3 with synthetic address data and network access disabled. They cover postcode lookup, selection, duplicate prevention, API errors and response formats, loaded sensors, local midnight rollover, offline schedule restoration and exhaustion, corrupt caches, storage failures, empty schedules, service discovery, options, and cleanup.

`scripts/package.py` builds `dist/guernsey_bin_night-<version>.zip` containing only the integration, README and license. HACS installs directly from the repository's `custom_components/` directory; the ZIP is also suitable for manual installation.

The GitHub workflow runs tests, Ruff, Home Assistant's hassfest, and HACS validation. Only HACS's `brands` check is skipped: a separate submission to `home-assistant/brands` is needed before default-catalog inclusion, but is not needed to load a custom repository. See [HACS integration requirements](https://www.hacs.dev/docs/publish/integration/) and [custom repositories](https://www.hacs.dev/docs/faq/custom_repositories/).

Before publishing, ensure the GitHub repository is public and has a description; keep personal configuration out of commits. For a release, update `manifest.json` and `pyproject.toml` together, run validation, and create a matching GitHub release. No repository or release is created by the packaging script.
