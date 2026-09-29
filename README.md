# Concilia Fiscal

Aplicação local em Streamlit para importar, validar e normalizar planilhas contábeis, fiscais e
de plano de contas. A interface Python também enriquece e classifica os lançamentos pelas regras
contábeis do baseline e classifica linhas fiscais pela elegibilidade do PIS. A interface web
apresenta somente a validação. Extração de nota fiscal e conciliação fiscal ainda não fazem parte
desta versão.

## Requisitos

- Python 3.13
- [uv](https://docs.astral.sh/uv/)

## Executar

```bash
uv sync
uv run streamlit run streamlit_app.py
```

Envie uma planilha `.xlsx` em cada campo. A validação começa somente quando os três arquivos
estiverem selecionados. Cada arquivo pode ter até 10 MiB; a estrutura interna expandida também
é limitada para reduzir o risco de arquivos maliciosos ou acidentalmente excessivos.

## Qualidade

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## Contratos atuais

| Arquivo | Aba | Colunas obrigatórias |
|---|---|---|
| Contábil | `Contabil` | `Código`, `Histórico`, `D/C`, `Vlr Saldo Final`, `CNPJ`, `Data`, `Número Lançamento` |
| Fiscal | `Fiscal` | `Alíquota PIS`, `Número Documento`, `Vlr Documento`, `Fornecedor`, `Data Fiscal` |
| Plano de contas | `Plano_Contas` | `Conta`, `Natureza Conta`, `Descrição Conta Societária`, `Tipo Conta` |

Colunas extras são aceitas e reportadas. Campos obrigatórios vazios, datas fora do formato
`YYYY-MM-DD` e decimais inválidos são apresentados com arquivo, linha física do Excel, coluna,
código estável e mensagem em português. Os dados lidos são preservados sem correção silenciosa.

## Normalização

`normalize_data(accounting, fiscal, accounts)` recebe três `ValidationResult` válidos e retorna
um `NormalizedData`. Os `DataFrame`s brutos não são alterados. Linhas vazias são omitidas e
`source_row` preserva a linha física do Excel. Colunas extras permanecem no bruto, mas não entram
na representação canônica.

| Tabela | Schema canônico |
|---|---|
| Contábil | `source_row: Int64`, `account_code: String`, `history: String`, `debit_credit: String`, `amount: Decimal(18,2)`, `cnpj: String`, `date: Date`, `entry_number: String` |
| Fiscal | `source_row: Int64`, `pis_rate: Decimal(18,2)`, `document_number: String`, `amount: Decimal(18,2)`, `supplier: String`, `date: Date` |
| Plano de contas | `source_row: Int64`, `account_code: String`, `account_nature: String`, `account_description: String`, `account_type: String` |

Textos são normalizados em Unicode NFC, maiúsculas e espaços uniformes, preservando acentos.
Datas viram `Date`; valores e alíquota de PIS viram `Decimal(18,2)` sem arredondamento. O PIS
permanece em pontos percentuais. Códigos preservam zeros à esquerda e pontuação. Documento fiscal
aceita somente dígitos; CNPJ aceita 14 dígitos ou a máscara `00.000.000/0000-00` e retorna apenas
dígitos. Formatos ambíguos produzem `NormalizationError` com todos os erros detectáveis, sem
resultado parcial.

## Enriquecimento pelo plano de contas

`enrich_accounting(data)` recebe um `NormalizedData` e retorna um `EnrichmentResult`. Cada
lançamento é associado exatamente pelo `account_code` já normalizado e recebe, ao final do
schema, `account_nature: String`, `account_description: String`, `account_type: String` e
`account_source_row: Int64`. A ordem e a quantidade dos lançamentos são preservadas, e nenhum
dos três frames normalizados de entrada é alterado.

Uma conta ausente mantém o lançamento com os quatro atributos enriquecidos nulos. Um código
duplicado no plano é sempre reportado, mesmo que não seja usado; lançamentos com esse código
também recebem atributos nulos para impedir associações ambíguas e multiplicação de linhas.
Essas situações produzem `EnrichmentIssue`s agrupadas e ordenadas pelo código, com as linhas
físicas afetadas nas duas fontes. O resultado permanece disponível integralmente, mas
`is_valid` será falso enquanto houver qualquer problema.

O enriquecimento não aplica filtros por natureza, tipo ou descrição, não exclui lançamentos e
não executa conciliação fiscal.

## Seleção contábil

`select_accounting(enrichment, config)` recebe um `EnrichmentResult` e retorna um
`SelectionResult` com o frame completo classificado, o subconjunto selecionado, as decisões
estruturadas por linha e os diagnósticos anteriores do enriquecimento. Os frames de entrada não
são alterados. A ordem original é preservada e cada lançamento recebe exatamente um estado:
`selected`, `excluded` ou `review`.

As regras exigem histórico e D/C preenchidos, excluem créditos e saldos menores ou iguais a zero
e aceitam somente natureza `04 - CONTAS DE RESULTADO` e tipo `A - ANALITICA`. As categorias
excluídas são procuradas como substring apenas na descrição da conta. A configuração padrão usa
`MATERIAL` e `MULTAS`; `SelectionConfig` permite substituir essa tupla ou desativar a regra com
uma tupla vazia.

Todos os motivos aplicáveis são registrados em ordem fixa por códigos estáveis. Dados que não
permitem uma decisão segura, como D/C desconhecido, saldo indisponível ou enriquecimento ausente,
levam a linha para `review`; uma exclusão contábil normal não invalida o resultado. As colunas
`selection_status: String` e `selection_reason_codes: List(String)` são anexadas aos frames de
saída. Esta etapa não consulta dados fiscais, não filtra PIS, não extrai NF e não realiza
conciliação.

## Classificação fiscal por PIS

`classify_fiscal(fiscal)` recebe o `DataFrame` fiscal normalizado e retorna um
`FiscalFilterResult` com o frame completo classificado, o subconjunto elegível e as decisões
estruturadas por linha. O frame de entrada não é alterado; sua ordem, quantidade, linhagem e
colunas são preservadas.

Somente linhas com `pis_rate` maior que zero recebem o estado `eligible`. Valores iguais a zero,
negativos ou nulos recebem `ineligible`. Cada linha registra exatamente um motivo estável:
`pis_positive`, `pis_zero`, `pis_negative` ou `pis_invalid`. As colunas
`fiscal_status: String` e `fiscal_reason_codes: List(String)` são anexadas aos frames de saída.

A função exige `source_row: Int64` sem valores nulos e `pis_rate: Decimal(18,2)`; violações desse
contrato interrompem a classificação com erro explícito, sem resultado parcial. Esta etapa não
extrai nota fiscal, não consulta ou concilia lançamentos contábeis e não altera a interface web.

## Fixtures fictícias

Os arquivos em `tests/fixtures/` são inteiramente fictícios e destinados exclusivamente a
desenvolvimento e testes:

- `contabil_teste.xlsx`
- `fiscal_teste.xlsx`
- `plano_contas_teste.xlsx`
- `resultado_esperado_teste.xlsx`

As fixtures cobrem seleção contábil e cenários futuros de conciliação, como match exato por NF e
valor, valor divergente, PIS zero, crédito, saldo negativo, categorias excluídas, natureza ou tipo
fora do escopo, risco de falso positivo de NF e histórico sem NF. Nenhum CNPJ, fornecedor ou
valor representa dados reais. `resultado_esperado_teste.xlsx` documenta resultados de etapas
futuras e não participa diretamente da validação.
