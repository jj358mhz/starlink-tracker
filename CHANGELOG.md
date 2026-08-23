# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] — 2026-08-22

### Added
- 🛰️ Favicon (satellite emoji) with full multi-device icon set (16px, 32px, 180px Apple, 192px & 512px Android, web manifest)
- 📸 App screenshot in README (`docs/screenshot.png`)
- ✨ Badges in README (release, build, deploy, container, license)
- 📝 Emoji-enhanced README for readability
- 📓 This changelog

## [1.0.0] — 2026-08-22

### Added
- 🌍 Real-time 3D visualization of the Starlink constellation via CesiumJS
- ⚡ Vectorized SGP4 propagation for ~10,000+ satellites (sub-second full-constellation compute)
- 🔭 Visible pass predictions for a configured observer, filtered to genuinely observable passes (observer in civil twilight or darker, satellite sunlit)
- 📍 Ground station marker on the globe
- 🎯 Click-to-fly camera navigation from sidebar to selected satellite
- 🖥️ FastAPI backend with `/positions`, `/passes`, `/health` endpoints
- 💾 In-memory caching (1s positions, 5min passes) with async computation to avoid blocking
- 🐳 Multi-arch Docker image (arm64 + amd64) on GitHub Container Registry
- 🚢 Full CI/CD pipeline: GitHub Actions builds image, SSH deploy workflow updates target host
- 🔒 MIT license

[Unreleased]: https://github.com/jj358mhz/starlink-tracker/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/jj358mhz/starlink-tracker/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/jj358mhz/starlink-tracker/releases/tag/v1.0.0
