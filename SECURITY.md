# Security policy

## Supported versions

Security fixes are made for the latest release only.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting ("Report a vulnerability" on the Security tab of this repository), or email hello@productreelabs.com.

Include the version, the steps to reproduce and the impact you expect. You will get an acknowledgement within five working days.

## Scope

Ìlú reads JSON from the Overpass API or from local files and writes model files. Of most interest are crashes or excessive resource use caused by crafted input, and anything that writes outside the output paths given.
