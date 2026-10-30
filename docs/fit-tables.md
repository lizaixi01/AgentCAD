# Verified dimensional fit table

The `iso_fit` library reads numeric ISO tolerance facts checked against SKF's
[Spherical plain bearings and rod ends, PUB BU/P1 06116/1 EN, May 2013](https://www.skf.com/binaries/pub12/Images/0901d19680154a05-06116_1-EN_tcm_12-122020.pdf),
printed page 74 (PDF page 76), tables 3 and 4. The source PDF is not redistributed.
The checked source file SHA-256 is
`df51e55192dc9ce138e371e2f5047cfbceeba7f2ac6246f92e5bd3d7f24930cb`.
This implementation covers only H7, h6 and g6 for nominal diameters above 10 mm
through 500 mm, including H7/h6 and H7/g6 pairs. It does not extrapolate other
classes, sizes or standards editions.

For 25 H7/g6, the hole limits are 25.000–25.021 mm; shaft limits are
24.980–24.993 mm; minimum/maximum clearance is 0.007/0.041 mm. These limits
describe dimensions; selecting a fit for load, thermal expansion, surface finish
or a particular bearing remains an engineering decision.

`src/agentcad/fits.py` retains the checked numeric rows, source revision and page.
`tests/test_y_tolerances.py` separately transcribes expected values and exercises
all ten upper-inclusive size boundaries, transitions, unsupported values and a
lookup-to-native-DIMENSION-to-file-readback workflow. The output uses mm even
when the drawing uses another unit. Numeric tolerance annotations do not claim
complete ISO drawing compliance.

Other standard-part tables have a separate [dimensional source audit](standard-tables.md).
It distinguishes verified dimensions, cutting-tool recommendations and unverified
counterbore data; neither audit certifies complete manufacturing compliance.
