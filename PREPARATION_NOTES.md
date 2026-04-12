This docoument is for Ian, to convert the Kleister Charity dataset raw data into a smaller useful subset for a playgroup session.

# Setup notes for Ian

```
cd /media/ian/data/playgroup_datasets/kleister-charity
git clone https://github.com/applicaai/kleister-charity.git
$ ./annex-get-all-from-s3.sh

dev-0$ xz -d in.tsv.xz # uncompress input data
# e.g. $ cut -f1 in.tsv | head -n 20 # list first 20 items
```

`utility/extract_copy_kleister_charity.sh` will do the copy and edit of files to `../data`.

## items reviewed

```
dev-0
pdf, pages, score on first 5 items, status, choose?
1ada336f29e8247f9f55a8d7e1b1c0da.pdf, 7, 2, clean, N - TRICK?
87ff1046fb88668ed4e0476d66abd733.pdf, 42
365a65c22610022110ca8610ecfe4034.pdf, 68
d07c46323bb61186b6175bad9a274225.pdf, 14, 5, scanned, Y
a84c1c7a3e570a716f6c61de557b5ff1.pdf, 18, 5, clean, Y
34646877386855695219579059c07302.pdf, 9, 5, scan, Y
bc1881761cdd5edf2d7e5c12958a82f2.pdf, 5, 5, scan, Y
48ec2c34cf13f32eb56baea66dbb665d.pdf, 46
00151bc74f2d59cecbed12e0d607a8e4.pdf, 20 (error in gold standard postcode)
cc9880ece943bf688b49359a8c219b04.pdf, 40, , slightly harder?
7d56c6cc848666198c050855dbb16092.pdf, 12, 5, scanned, Y
bfd08fe466e142006e4a04e9630d4579.pdf, 39, , USD?! (includes GBP/USD but that seems silly?)
c1e453df06418b5289b40d04729a09c5.pdf, 18, clean
44ba842bbbd4f18587ad8ae3fe4ecdd7.pdf, 54, 5, scan, HARD-Y
6f9b8f27fd43be13d822c0b4654be167.pdf, 6, , could have been good 'this year last year' but has a typo in gold std Y(needs fix) Y
556ee39a83d9a15738918e8e60dc45a7.pdf, 20, 5, clean, HARD-Y
cfe956d594cd45a0267d966dadebf72e.pdf, 72, 5, clean, HARD-Y (000 summary of numbers)
cc19e4fd0c4a605a7f537050df52483e.pdf, 15, 5, scan (offset), EASY-Y
0d45add2d94d80a0eb85e41e22aa43a0.pdf
762f74d04c9fd0a99b2776603704267b.pdf

```

## Fixes

`Hitchin_Education_Foundation charity_number` needs postcode SG18_9N4 -> SG18_9NR.
`Yorkshire_Federation_Of_Young_Farmers'_Clubs` needs an incoming funds of 107771.00 -> 107711.00 

# Things we could test

* calling llm_openrouter with an unknown model name, only_providers should raise
* extractor / score parity: a completed V7 run (`playgroup_dev_extracted__v7__*.tsv`) should appear in `python score.py` alongside OpenRouter and Doubleword rows (`provider` = `v7`)

# Future topics?

* get attribution for each page?