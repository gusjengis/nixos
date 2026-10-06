# Office LiDAR Tile Lookup

Use when asked to find LiDAR covering a job parcel and copy it into the job.

## Paths

- Jobs: `/mnt/office/company/Jobs/Jobs/<job>`.
- Ortho drive: `/mnt/office/orthos`.
- LiDAR source: `/mnt/office/orthos/LiDAR`.
- Destination: `<job>/Autocad/LiDAR` unless user specifies otherwise.
- Source files are large `.txt` point clouds, not necessarily LAS/LAZ. Observed rows: `easting northing elevation classification`, space-separated, no header.
- Dataset attribution: `0_DATASET_REPORT(lidarportal.dnr.wa.gov).csv` in source directory. Do not read whole point clouds into conversation.

## Fast Lookup

1. Identify parcel number from job documents, especially `Data` site plans, staff reports, contracts, or county maps. PDF images may contain parcel numbers even when text extraction fails. Confirm address and parcel against documents.
2. Query Pierce County's hosted parcel layer directly. Avoid enumerating all services or relying on `gis.piercecountywa.gov`, which failed during this task.

   Endpoint: `https://services2.arcgis.com/1UvBaQ5y1ubjUPmd/ArcGIS/rest/services/Tax_Parcels/FeatureServer/0/query`

   Parameters: `where=TaxParcelNumber='<parcel>'`, `outFields=TaxParcelNumber,Site_Address`, `returnGeometry=true`, `outSR=2927`, `f=pjson`.

   Example:

   ```sh
   curl --fail --get 'https://services2.arcgis.com/1UvBaQ5y1ubjUPmd/ArcGIS/rest/services/Tax_Parcels/FeatureServer/0/query' \
     --data-urlencode "where=TaxParcelNumber='3605001390'" \
     --data-urlencode 'outFields=TaxParcelNumber,Site_Address' \
     --data-urlencode 'returnGeometry=true' \
     --data-urlencode 'outSR=2927' \
     --data-urlencode 'f=pjson'
   ```

3. Reject API errors or empty features. Get min/max X/Y from all polygon rings, not just parcel centroid. EPSG:2927 is NAD83(HARN) / Washington South (US survey feet). Observed local tile coordinates align with this parcel coordinate system; recheck if source format/dataset changes.
4. Observed tile grid: 3,000 feet square. Eight-digit filename is four digits of west easting / 1,000 followed by four digits of north northing / 100. Example `11965660.txt`: X `[1196000,1199000]`, Y `[563000,566000]`. Filename Y denotes NORTH edge, not south edge. Grid origin is not zero: observed west edges are congruent to 2,000 modulo 3,000; north edges are congruent to 2,000 modulo 3,000.
5. For a point `(x,y)`, candidate west edge is `2000 + 3000 * floor((x-2000)/3000)`; north edge is `2000 + 3000 * (floor((y-2000)/3000)+1)`. Filename: concatenate integer `west/1000` and zero-padded four-digit integer `north/100`, then `.txt`. Enumerate every cell intersecting full parcel bounding box; using bbox may conservatively include extra tiles for irregular parcels. Include adjacent cells if parcel touches an edge; inspect polygon overlap when avoiding extra copies matters.
6. Check candidate exists, is nonempty, and is not `.nodata`. Read only a few rows, then stream candidate to verify actual XY bounds and presence of points near parcel. Do not recursively scan every point cloud. If grid assumption fails, investigate source metadata/tile index instead of guessing.

## Copy and Verify

- Check destination parent exists. Create `Autocad/LiDAR` if needed.
- Copy originals unchanged. Do not move source, clip, reproject, or rename without request.
- Avoid overwriting existing user files; compare them first. A partial copy created by your own timed-out command may be replaced to finish the operation.
- Network copy can take over two minutes. Use at least 600,000 ms tool timeout for copy plus verification.
- Compare source/destination sizes and SHA-256 hashes. Do not report completion until hashes match.
- Report parcel, filenames, destination, and verification. No commit/rebuild needed for workflow note unless requested.

## Verified Example: Job 3572

- Job: `3572 - Out & About Eatonville`.
- Parcel: `3605001390`, `106 CENTER ST W`.
- Document evidence: `Data/Staff Report - Out & About Burgers CUP - SIGNED.pdf`, page 2; highlighted site in `Data/CountyView.pdf`.
- County polygon bbox (EPSG:2927): X `1198264.3634` to `1198356.3407`, Y `564386.8873` to `564489.4449`.
- One covering tile: `11965660.txt`.
- Actual point bounds: X `1196000.000` to `1198999.999`, Y `563000.000` to `565999.997`.
- Tile has 4,385,299 points; 6,527 fall inside parcel bbox (bbox count, not exact polygon count).
- Copied to job's `Autocad/LiDAR/11965660.txt`; 149,113,316 bytes.
- Source/destination SHA-256: `0ac3016c171a220a405bd4392542b7842a7e195d92ebfc6444ada1dca2abd77d`.
