# Arquitetura dos scrapers

O nucleo do sistema nao conhece detalhes de cada site. Cada fonte implementa a interface comum `AuctionScraper` e retorna lotes normalizados como `RawLot`.

## Contrato

Cada scraper deve informar:

- `source_name`: nome da origem.
- `fetch_lots()`: iteravel de lotes encontrados.

O scraper deve:

- respeitar timeouts;
- usar rate limit razoavel;
- retornar apenas dados presentes na fonte;
- nao inventar identificadores;
- preencher `external_id` com um identificador estavel quando houver;
- usar a URL como parte da identidade quando nao houver ID oficial.

## Escolha por tipo de fonte

- API publica: preferencial, mais estavel e menos custosa.
- API interna: usar apenas se permitido pelos termos e com limites conservadores.
- HTML tradicional: coletar com HTTP e parser dedicado ao site.
- JavaScript pesado: usar navegador headless somente nesse adaptador.
- Autenticacao: guardar secrets em variaveis de ambiente.

## Idempotencia

A chave unica e composta por:

```text
source_site + external_id
```

Se o mesmo lote aparecer novamente, o registro existente e atualizado. Mudancas relevantes geram historico em `lot_changes` e lances em `bid_history`.

## Exemplo

```python
from auction_monitor.models import RawLot
from auction_monitor.scrapers.base import AuctionScraper

class MeuLeilaoScraper(AuctionScraper):
    source_name = "meu-leilao"

    def fetch_lots(self):
        yield RawLot(
            title="Titulo vindo da fonte",
            url="https://exemplo.com/lote/123",
            external_id="123",
            source_site=self.source_name,
            current_bid=35000,
        )
```

Depois registre o scraper em `build_scrapers()` dentro de `auction_monitor/service.py`.

