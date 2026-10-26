# Small published Hydraflow cases

Collected 2026-10-25. These are public engineering-report excerpts produced by older Hydraflow versions. They provide reported vendor results, not proof that 2027 uses identical defaults or algorithms. Each source PDF is retained locally; the Express and Storm excerpts are also saved as short PDFs. Treat displayed values as rounded.

Source PDF SHA-256: Express `501657668C9F4254DA3ACD7C2E5F508F6B67AAA2CABC4705CB482EDCE5344D09`; Hydrographs `0EE092BD5311C8B370BB605C633A4F64AD5BAB0C8CEEEFB9F886601CED93C600`; Storm Sewers `C43DACAB5E050AA693C3409D9D9A5988CE440F9BFB2C9A6BB11FA91801A53D9E`.

| Product | Case and source | Reproducibility | Useful checks |
| --- | --- | --- | --- |
| Express | [Rectangular weir](Express-rectangular-weir-case.pdf), source PDF p. 140 ([public report](https://epcdevplanstorage.blob.core.windows.net/project/1e740e13-95df-43f4-bafb-1afe5e85e851/47025e01-cfe4-4f2f-bc76-477a4b08d872.pdf)) | Complete for the reported sharp-crested known-Q weir case | Length 0.90 ft, `Cw=3.33`, `Q=5.25 cfs`; report depth 1.45 ft, area 1.31 ft², velocity 4.01 ft/s. `H=(Q/(Cw L))^(2/3)` gives 1.453 ft. |
| Hydrographs | Rational runoff, source PDF p. 58 ([public report](https://epcdevplanstorage.blob.core.windows.net/project/1fbd79ed-7dc4-4a7b-9933-e9dcdb12d93e/29b45105-8afc-4448-a62a-2957139e9ee2.pdf)) | Complete for the hydrograph **given the printed intensity**; original Colorado Springs IDF file unavailable | Area 8.170 ac, `C=0.39`, `Tc=14 min`, intensity 3.693 in/hr, 1-min interval, limbs 1/1; report peak 11.77 cfs and volume 9,884 ft³. Current Pro-Flow gives 11.767 cfs and 9,884.285 ft³. |
| Storm Sewers | [One-line outfall](Storm-one-line-case.pdf), source PDF pp. 46-47 ([public report](https://online.wichita.gov/LFWebDocs/Home/GetStormwaterDoc/220496)) | **Partial**; roughness, starting HGL/tailwater, and other design settings are absent | One 148-ft, 18-in line; area 2 ac, `C=0.48`, `Tc=15 min`, 0.33% pipe slope; report `Q=7.07 cfs`, full capacity 5.99 cfs, HGL 1389.77/1390.85 ft. Use for format/result reconnaissance, not a strict solver-parity gate. |

The Hydrographs report also has a reservoir result on PDF p. 59 (5-year peak 1.945 cfs, maximum storage 8,695 ft³), but the pond's stage-storage-discharge inputs are not on that page. It is a later output comparison once those inputs are recovered.

The Storm Sewers report prints an FHA IDF equation (`62.28 / (Tc + 10.10)^0.66`) and an intensity rounded to 7.4 in/hr. Evaluating that equation at 15 min gives about 7.423 in/hr; multiplying by the printed area and `C` gives about 7.126 cfs, versus the reported 7.07 cfs. The displayed inputs do not fully reconstruct the reported flow, so do not tune the solver to this row.

The executable check for the Hydrographs Rational case is in `../../proflow-main/tests/test_rational.py`. The next fixture pass should add current-version output from the signed 2027 binaries and independent textbook/agency calculations, then compare with explicit tolerances.
