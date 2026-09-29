# Concilia Fiscal

Aplicação local em Streamlit para importar e validar planilhas contábeis, fiscais e de plano
de contas. Esta primeira feature verifica os contratos dos arquivos e apresenta todos os erros
detectáveis com segurança. Regras de conciliação ainda não fazem parte desta versão.

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

## Fixtures fictícias

Os arquivos em `tests/fixtures/` são inteiramente fictícios e destinados exclusivamente a
desenvolvimento e testes:

- `contabil_teste.xlsx`
- `fiscal_teste.xlsx`
- `plano_contas_teste.xlsx`
- `resultado_esperado_teste.xlsx`

As fixtures futuras de conciliação cobrem match exato por NF e valor, valor divergente, PIS
zero, crédito, saldo negativo, categorias excluídas, natureza ou tipo fora do escopo, risco de
falso positivo de NF e histórico sem NF. Nenhum CNPJ, fornecedor ou valor representa dados
reais. `resultado_esperado_teste.xlsx` está armazenado para features futuras e não participa
da validação atual.
