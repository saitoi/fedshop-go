# Query Engine Source References

This directory stores current source checkouts used as references for the
FedShop benchmark and for the planned minimal Go engine.

The initial clone set is:

| Directory | Source | Notes |
| --- | --- | --- |
| `rdf4j-fedx` | `https://github.com/eclipse-rdf4j/rdf4j.git` | Current FedX is part of RDF4J. FedShop's old adapter is not directly compatible. |
| `CostFed` | `https://github.com/AKSW/CostFed.git` | CostFed / Quetzal implementation. |
| `semagrow` | `https://github.com/semagrow/semagrow.git` | SemaGrow federated query processor. |
| `splendid-server` | `https://github.com/semagrow/fork-splendid-server.git` | SPLENDID implementation used by Semagrow tooling. |
| `anapsid` | `https://github.com/anapsid/anapsid.git` | ANAPSID adaptive engine. Requires Python 2 for FedShop adapter. |
| `fedup` | `https://github.com/GDD-Nantes/fedup.git` | FedUP and HiBISCuS experiment code. |
| `sevod-scraper` | `https://github.com/semagrow/sevod-scraper.git` | SemaGrow summary generation helper. |
| `watdiv` | `https://github.com/mhoangvslev/watdiv.git` | FedShop data generator dependency. |
| `FedShop-proxy` | `https://github.com/mhoangvslev/FedShop-proxy.git` | Proxy used by FedShop evaluation. |

Refresh all checkouts with:

```bash
scripts/clone-query-engines.sh
```
