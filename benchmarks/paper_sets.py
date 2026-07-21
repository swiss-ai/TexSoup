"""Small redistributable arXiv paper sets for the benchmark harness.

Only include papers whose licenses were verified from the local/RCP Cornell
arXiv metadata snapshot with ``interleaved-arxiv-analysis/src/arxiv_license``
policy. Do not add unverified arXiv IDs to committed benchmark sets.

The full benchmark suite is intentionally external: publish it as a HF dataset
or equivalent artifact with source packages, license metadata, feature flags,
and a paper-set manifest. Keep this repository to the harness plus a small
redistributable smoke set.
"""

REDISTRIBUTABLE_SMOKE_10 = (
    '2106.11235',
    '2410.12841',
    '2304.11345',
    '1903.07070',
    '2504.07841',
    '2103.03147',
    '2312.11442',
    '2401.04569',
    '2209.09444',
    '2208.01523',
)

PAPER_SET_LICENSES = {
    '1903.07070': 'http://creativecommons.org/licenses/by/4.0/',
    '2103.03147': 'http://creativecommons.org/licenses/by/4.0/',
    '2106.11235': 'http://creativecommons.org/licenses/by/4.0/',
    '2208.01523': 'http://creativecommons.org/licenses/by/4.0/',
    '2209.09444': 'http://creativecommons.org/publicdomain/zero/1.0/',
    '2304.11345': 'http://creativecommons.org/licenses/by/4.0/',
    '2312.11442': 'http://creativecommons.org/licenses/by/4.0/',
    '2401.04569': 'http://creativecommons.org/licenses/by/4.0/',
    '2410.12841': 'http://creativecommons.org/licenses/by/4.0/',
    '2504.07841': 'http://creativecommons.org/licenses/by/4.0/',
}

PAPER_SETS = {
    'redistributable-smoke-10': REDISTRIBUTABLE_SMOKE_10,
    'redistributable-stress-10': REDISTRIBUTABLE_SMOKE_10,
}
