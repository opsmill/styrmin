# Driver Specification File Contract: `spec.info`

The format driver authors write in `driver.styrmin.yml`. Documented in `driver/DRIVERS.md` and `docs/docs/drivers/creating-a-driver.md`.

```yaml
spec:
  info:                                   # optional
    icon: https://docs.infrahub.app/img/infrahub-logo.svg   # optional
    description: Next generation source of truth for infrastructure management  # optional
    links:                                # optional
      - link: Homepage                    # label text
        url: https://www.opsmill.com/
      - link: Documentation
        url: https://docs.infrahub.app
    authors: [opsmill]                    # optional, accepted, not shown
    license: Apache-2.0                   # optional, accepted, not shown
```

| Key | Format | Where it appears | Change |
|-----|--------|------------------|--------|
| `icon` | Absolute `http`/`https` URL of an image. Square SVG or PNG recommended (shown at 32×32 px or smaller). | Driver list (group header and flat rows), driver detail header | Now validated and stored |
| `description` | Text. Line breaks kept on the detail page. | Driver list group header (one line), driver detail page | Now stored |
| `links` | List of entries with exactly `link` (label) and `url` (absolute `http`/`https` URL). | Driver detail page, Overview tab | Now validated and stored |
| `authors` | List of strings | Not shown | Unchanged |
| `license` | String | Not shown | Unchanged |

## Behavior the author needs to know

- Styrmin does not download the image. Each person who opens the driver pages loads it from `icon` in their own browser, so the URL must be reachable from those browsers. In an installation without internet access, host the image on an internal server or leave `icon` out.
- When the image cannot be loaded, the pages show the generic package icon.
- The browser does not send the Styrmin page address to the image host, but the host still receives a request with the IP address of each viewer. Use an image host you trust.
- Changing `info` changes the specification file. For a local driver, that changes the content hash, so the load creates a new driver version. For a Git driver, it needs a new commit, which creates a new driver version.

## Breaking change for driver files

Before this change, any string was accepted for `icon`, and any string map for each `links` entry. Now the load fails when:

- `icon` is not an absolute `http`/`https` URL (for example the old placeholder `xxxx`).
- A `links` entry has keys other than `link` and `url`, misses one, or has a `url` that is not an absolute `http`/`https` URL.

Driver versions already stored are not checked again.
