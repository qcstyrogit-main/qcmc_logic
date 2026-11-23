-- Read-only SQL Server extraction. First row per trimmed item wins.
-- Count all non-null values, including zero; nonpositive winners are not imported.
SELECT RTRIM(LTRIM(cProdCode)) AS item_code,
       nStdPackQty AS quantity,
       COUNT(*) AS occurrences
FROM MRP.dbo.M_prodstandard
WHERE cProdCode IS NOT NULL AND nStdPackQty IS NOT NULL
GROUP BY RTRIM(LTRIM(cProdCode)), nStdPackQty
ORDER BY RTRIM(LTRIM(cProdCode)), COUNT(*) DESC, nStdPackQty ASC
