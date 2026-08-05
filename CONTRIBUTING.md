# Contributing

Contributions are welcome, including bug reports, documentation improvements,
device support and fixes to existing behaviour.

## Reporting issues

Use [GitHub Issues](../../issues) for reproducible bugs and feature requests.
Before opening an issue, search the existing open and closed issues and provide
the information requested by the relevant template.

Do not disclose a security vulnerability in a public issue. Follow the private
reporting process in [SECURITY.md](SECURITY.md) instead.

## Pull requests

1. Fork the repository and create a focused branch from `main`.
2. Keep unrelated fixes in separate pull requests.
3. Add or update tests where practical.
4. Run the lint and formatting checks.
5. Test the change against relevant Delta Dore hardware when possible.
6. Update the documentation. If a change affects the README, update both
   `README.md` and `README.fr.md`.
7. Open a pull request and complete its checklist.

Please describe the observed behaviour, the proposed change and the testing
performed. Remove credentials, PINs, tokens, MAC addresses and other personal
information from logs before attaching them.

## Code quality

The continuous-integration workflow uses Ruff. Run the same checks locally:

```bash
python3 -m pip install -r requirements.txt
python3 -m ruff check custom_components/
python3 -m ruff format custom_components/ --check
```

Run the tests relevant to your change in your development environment. New
protocol or entity behaviour should normally include a regression test under
`tests/`. For hardware-dependent changes, include sanitised logs and state
which device and operations were tested.

## Licence

By contributing, you agree that your contribution will be licensed under the
repository's [MIT Licence](LICENSE).
