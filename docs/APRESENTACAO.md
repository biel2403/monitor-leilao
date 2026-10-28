# Apresentacao no computador do cliente

GitHub armazena o codigo; ele nao executa este servidor Python. O Docker executa
o painel e a coleta no computador do cliente. Para acesso apenas por link,
sera necessario hospedar o servidor; esta configuracao e para demonstracao local.

1. Instale e abra o Docker Desktop no computador do cliente.
2. Leve a pasta do projeto com Dockerfile, compose.yaml, auction_monitor, web e samples.
3. Configure um arquivo .env nessa pasta usando .env.example como referencia.
   As chaves OpenRouter e ReefAPI ficam somente nesse arquivo, fora do GitHub.
4. Abra um terminal na pasta e execute `docker compose up -d --build`.
5. Acesse http://localhost:8080 no navegador. A primeira coleta pode levar alguns minutos.

Para parar: `docker compose down`. Para acompanhar erros: `docker compose logs --tail=100`.
Os lotes e configuracoes ficam em um volume persistente. Nao use `down -v` para
parar, pois isso apaga o volume. A demonstracao inicia com um banco novo e coleta
os lotes; nao inclui as analises salvas no computador de desenvolvimento.

A analise depende da disponibilidade do modelo no OpenRouter. Uma chave valida
nao garante capacidade nos modelos gratuitos. O painel informa as falhas.

O custo estimado inclui lance, comissao e despesas conhecidas. Reparos, transporte
e custos nao publicados nao estao incluidos. Sem taxas consultadas, nao ha total.
