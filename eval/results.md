# Claim-checker evaluation

34 labelled claims, judged fresh by Gemini.

| outcome | count |
|---|---:|
| false confirmations | **1** |
| missed confirmations | 7 |
| wrong source credited | 1 |
| correct | 25 |

A false confirmation is the one that reaches air: the system called a
figure confirmed when the retrieved pages do not establish it.

| case | group | verdict | status reached | credited | should credit |
|---|---|---|---|---|---|
| AIスマート弁当箱の価格は1980円 | fictional_product | ok | UNVERIFIED | — | — |
| コンビニエンスストアは今全国に約5万6000点あります。 | jp_store_count | missed | UNVERIFIED | — | — |
| この商店街のお店の数が随分減った | speakers_own | ok | UNVERIFIED | — | — |
| この商店街の喫茶店は40年近く営業している | speakers_own | ok | UNVERIFIED | — | — |
| 全国に80店舗で販売 | fictional_product | ok | UNVERIFIED | — | — |
| 全国のコンビニエンスストアは約5万6000店あります。 | jp_store_count | missed | CONFLICTING | — | — |
| コンビニエンスストアは全国におよそ5万6000店ある | jp_store_count | missed | CONFLICTING | — | — |
| 喫茶店の営業期間は40年近く | speakers_own | ok | UNVERIFIED | — | — |
| AIスマート弁当箱が中身の栄養バランスを自動で記録する。 | fictional_product | ok | UNVERIFIED | — | — |
| Small businesses in this country employ almost h | us_public_record | missed | UNVERIFIED | — | advocacy.sba.gov |
| The federal minimum wage is $7.25 an hour. | us_public_record | ok | MULTIPLE_SOURCES_CONFIRMED | www.dol.gov | www.dol.gov |
| 日本のお持ち帰り商品に対する消費税は8%である | jp_tax_8 | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| お持ち帰りの消費税は8% | jp_tax_8 | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| There are more than 150,000 convenience stores i | us_public_record | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| 日本における店内飲食に対する消費税は10%である | jp_tax_10 | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| AIスマート弁当箱は中身の栄養バランスを自動で記録する。 | fictional_product | ok | UNVERIFIED | — | — |
| 店内飲食消費税率は10% | jp_tax_10 | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| 価格は1980円です。 | fictional_product | ok | UNVERIFIED | — | — |
| お持ち帰り消費税率は8% | jp_tax_8 | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| The federal minimum wage of $7.25 an hour has no | us_public_record | wrong source credited | MULTIPLE_SOURCES_CONFIRMED | www.bls.gov | www.dol.gov |
| お持ち帰りの消費税率は8% | jp_tax_8 | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| 店内で召し上がりの消費税率は10% | jp_tax_10 | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| 現在全国に80店舗で販売しています。 | fictional_product | ok | UNVERIFIED | — | — |
| AIスマート弁当箱は新しい商品である。 | fictional_product | ok | UNVERIFIED | — | — |
| コンビニエンスストアは全国に約5万6000点ある | jp_store_count | missed | UNVERIFIED | — | — |
| AIスマート弁当箱は現在全国80店舗で販売 | fictional_product | ok | UNVERIFIED | — | — |
| コンビニエンスストアは全国に約5万6000店ある | jp_store_count | missed | UNVERIFIED | — | — |
| コンビニエンスストアの店舗数は全国に約5万6000店 | jp_store_count | missed | UNVERIFIED | — | — |
| 店内で召し上がりの消費税は10% | jp_tax_10 | ok | MULTIPLE_SOURCES_CONFIRMED | — | — |
| AIスマート弁当箱は中身の栄養バランスを自動で記録してくれる | fictional_product | FALSE CONFIRMATION | MULTIPLE_SOURCES_CONFIRMED | pubmed.ncbi.nlm.nih.gov | — |
| convenience stores nationwide: Nearly all conven | us_generalisation | ok | UNVERIFIED | — | — |
| AIスマート弁当箱は全国に80店舗で販売されている | fictional_product | ok | UNVERIFIED | — | — |
| AIスマート弁当箱は現在全国に80店舗で販売されている | fictional_product | ok | UNVERIFIED | — | — |
| AIスマート弁当箱は現在全国80店舗で販売されている | fictional_product | ok | UNVERIFIED | — | — |
