# Manual de utilização do sistema

Guia de uso do sistema de gestão, em linguagem simples. O nome, as cores e o logo que aparecem nas telas são os da sua empresa (configurados em `marca.json`).

- **Endereço:** o endereço do seu sistema, definido na instalação.
- **Quem usa:** a administração, as prestadoras de serviço e a contabilidade, cada uma vendo só o que o seu perfil permite.

---

## 1. Primeiros passos

### 1.1 Entrar e sair
1. Abra o endereço do sistema e informe o **e-mail** e a **senha**.
2. Marque **Manter conectado** só em computador seu.
3. Para sair, use **Sair** no alto do menu lateral.

### 1.2 Trocar a senha
No menu lateral, ao lado do seu nome, clique no **ícone de chave**. Informe a senha atual, a nova (mínimo de 8 caracteres) e repita a nova.

### 1.3 Perfis de acesso
| Perfil | O que vê |
|---|---|
| **Administradora** | Tudo, inclusive Usuários e Permissões. |
| **Prestadora de serviço** | Só as áreas liberadas pela administração e as suas notas fiscais ("Minhas Notas Fiscais"). |
| **Contabilidade** | Só consulta dos repasses e do ISS do mês (notas emitidas). Não vê dados clínicos das clientes. |

Se uma tela não aparecer no seu menu, o seu perfil não tem acesso a ela. Peça à administração para liberar.

### 1.4 Como o menu é organizado
**Principal** (Dashboard) · **Cadastros** (Clientes, Atendimentos, Planos de Contrato, Procedimentos, Materiais, Centros de Custo) · **Financeiro** (Lançamentos, Contas a Receber, Contas a Pagar, Nota Fiscal, ISS do Mês, DRE, Fluxo de Caixa, Relatório de Faturamento) · **Recursos Humanos** (Folha de Pagamento, Notas das Prestadoras, Minhas Notas Fiscais) · **Gerência** (Relatório Gerencial, Contratos × ISS, Conta Bancária, Caixa da Empresa, Formas de Pagamento) · **Administração** (Usuários e Permissões).

### 1.5 Dica geral
Antes de apagar ou cancelar, prefira **cancelar/anular**: o registro fica guardado para consulta. Em dinheiro, quase tudo pode ser **desfeito** (ver o capítulo 13).

---

## 2. Dashboard (tela inicial)

Mostra o que precisa de atenção hoje:
- **Alerta de 36ª semana com pagamento pendente:** gestantes que entraram na 36ª semana sem terem pago o contrato (só aparece para quem tem acesso ao financeiro).
- **Partos sem pagamento:** clientes que já tiveram o parto e ainda devem o contrato (também só para o financeiro).
- **Próximos partos** e **Gestantes em acompanhamento:** semana de gestação, 1ª e 2ª consulta da enfermeira obstetra (EO), médico, grupo/plantão, hospital e situação do contrato. Dali você **agenda** ou **registra** as consultas.
- **Próximos atendimentos:** com os botões **Confirmar** (marca como realizado) e **Remarcar**.
- **Resumo do mês atual** no regime de caixa.

---

## 3. Clientes (gestantes)

### 3.1 Lista
Filtros: **Buscar** (nome), **Status** (gestante, puérpera, inativa), **Ano**, **Tipo de parto** e **Pagamento**. Cada linha mostra DPP, data do parto, tipo, médico, grupo/plantão, hospital, bebê e contrato.

### 3.2 Cadastrar uma cliente
**Clientes > Novo.** Preencha:
- Nome completo (obrigatório), CPF, data de nascimento, nome do bebê.
- **DPP** (data prevista do parto), data do parto real (quando já houver) e tipo de parto.
- Status, médico pré-natalista, grupo de parto/plantão, hospital do parto.
- **Ano de referência** e **status do contrato** (pendente, enviado, assinado).
- **Plano:** ao escolher um plano, o valor do contrato é preenchido sozinho. Dá para criar um plano novo ali mesmo.
- **Pagamento:** valor, forma, operadora, parcelas e data do pagamento. **Data em branco = pendente** (a cliente ainda vai pagar). Dá para adicionar mais de uma forma de pagamento.

Ao salvar, o sistema cria os **lançamentos do contrato** (o que a cliente vai pagar ou já pagou).

### 3.3 Nome repetido
Se já existir uma ficha com o mesmo nome, o sistema avisa e mostra a ficha existente com a referência (data do parto, DPP ou ano do contrato). Se for **uma nova gestação**, confirme para criar outra ficha: cada gestação tem a sua ficha. Nas listas, fichas com o mesmo nome aparecem com a referência ao lado do nome.

### 3.4 Registrar o parto
Na lista ou no painel: **Registrar parto**, informe a **data do parto** (e o tipo). O sistema:
- muda a cliente para **puérpera**;
- passa a competência dos lançamentos do contrato para o mês do parto (o vencimento dos pendentes passa a ser a data do parto).

**Registre o parto assim que acontecer:** é ele que coloca o contrato na Folha do mês certo.

### 3.5 Ficha da cliente
Mostra dados pessoais, acompanhamento obstétrico, plano contratado, dados do contrato, resumo financeiro, atendimentos e lançamentos (competência, bruto, forma, taxa, líquido real e pagamento). **Excluir cliente** apaga tudo da cliente e pede confirmação.

---

## 4. Atendimentos

### 4.1 Agendar
**Atendimentos > Novo.** Escolha a cliente, data, horário, tipo e profissional/EO, adicione os **procedimentos** e salve. O atendimento fica **agendado**.

**Consulta rápida (pelo painel):** a 1ª e a 2ª consulta da EO incluídas no plano são agendadas sem custo e sem lançamento financeiro. Ao confirmar, a cliente sobe para o quadro de gestantes em acompanhamento.

### 4.2 Realizar, cancelar, remarcar, excluir
- **Marcar como realizado:** o sistema gera um **lançamento de receita pendente** para cada procedimento.
- **Cancelar:** cancela o atendimento e os lançamentos que ainda estavam pendentes.
- **Remarcar:** muda a data.
- **Excluir:** apaga o atendimento **e** os lançamentos dele. Use só em caso de erro.

### 4.3 Receber um atendimento
No atendimento, em **Lançamentos financeiros**, clique **Receber**: informe a data, a forma de pagamento, a operadora e as parcelas (cartão). Veja o capítulo 6.3.

### 4.4 "Valor vai para" (só a administração)
Define se o valor do atendimento vai para o **rateio da Folha** (padrão) ou **somente para uma prestadora**. Este campo e a informação de para quem vai o valor são vistos **só pela administração**.

---

## 5. Cadastros de apoio

- **Planos de Contrato:** nome, valor, quantas parcelas sem taxa e os serviços incluídos (com quantidade). **Desativar** um plano o tira das opções sem apagar a história.
- **Procedimentos:** código, nome, categoria, valor padrão, centro de custo e ativo. O valor padrão é usado nos atendimentos.
- **Materiais:** estoque com código, unidade, valor, quantidade atual e mínima. Em **Movimentar**, registre **entrada** ou **saída** (quantidade, valor, data, motivo). Abaixo do mínimo, o material fica em alerta.
- **Centros de Custo:** as categorias do financeiro (código, nome e tipo: receita, despesa ou ambos). Toda receita e despesa deve ter um centro de custo: ele alimenta o DRE e os relatórios.

---

## 6. Financeiro

### 6.1 Lançamentos
Lista tudo que entra e sai, com filtros de **regime** (caixa ou competência), **mês**, **tipo**, **status** e **centro de custo**.

**Novo lançamento:** descrição, tipo (receita/despesa), valor, **data de competência** (mês a que pertence), **data de vencimento**, data de pagamento, status, **centro de custo**, cliente (opcional), forma de pagamento, número do documento e observações.

**Despesa recorrente** (repete todo mês): marque "despesa recorrente", escolha o **dia do mês** (ou "último dia do mês") e, se quiser, **valor = % do lucro bruto do mês** (por exemplo, a Administração com 10%). O sistema cria a despesa de cada mês como pendente.
- Para mudar o valor dos próximos meses ou parar a recorrência, edite a **despesa original**. Não apague o lançamento recorrente original: ele gera os meses seguintes.
- A despesa em % do lucro bruto usa o lucro bruto **da Folha**. Ela é lançada como **paga** automaticamente quando a Folha do mês é fechada (capítulo 9).

**Lançamento liquidado** (recebido ou pago): só **descrição, observações e centro de custo** podem ser alterados. Para corrigir valor ou data de uma despesa paga, use **Desfazer pagamento** (capítulo 13).

**Cancelar** um lançamento pendente o tira dos totais, mantendo o registro.

### 6.2 Contas a Pagar
Lista as despesas, por padrão as **pendentes**; há filtros **Pendentes / Pagos / Todos**.
- As despesas vêm agrupadas **por mês de vencimento**, com uma linha que mostra o mês e o **total do mês**.
- **Pagar:** informe a data e a forma de pagamento. A despesa passa a **paga** e sai do caixa nessa data.
- Despesas geradas pela Folha fechada aparecem com um cadeado (**Folha**) e não podem ser alteradas.

### 6.3 Contas a Receber
Lista o que as clientes ainda vão pagar. Em **Receber**, informe a **data do recebimento**, a **forma**, a **operadora** e as **parcelas** (cartão). O sistema calcula a **taxa** e o **valor líquido** que entra de verdade.

**Taxa de cartão automática:** ao receber por cartão ou link, o sistema lança sozinho a despesa da taxa da operadora. Se o recebimento mudar, a taxa é recalculada. Não é preciso lançar a taxa à mão.

### 6.4 Regime de caixa x competência
- **Caixa:** conta o dinheiro pela **data em que entrou ou saiu** (padrão do sistema).
- **Competência:** conta pelo **mês a que o lançamento pertence**.

---

## 7. Notas fiscais e ISS

### 7.1 Regras
- Notas emitidas até **31/12/2025** saíram no sistema **municipal**; de **2026** em diante, no sistema **nacional**. As duas numerações podem se repetir; identifique a nota por **número + sistema**.
- **ISS de 6%**, com **vencimento no dia 20 do mês seguinte** à emissão. Uma nota emitida em 17/11 tem o ISS vencendo em 20/12.
- Notas anteriores a 2026, trazidas de um histórico, não têm lançamento de ISS no sistema.

### 7.2 Tela Nota Fiscal
No topo: **recebimentos sem nota**, **impostos a pagar** e **impostos pagos no mês**.

**Importar pelo XML (recomendado):** envie os arquivos XML da prefeitura. O sistema lê número, datas, valor e chave de acesso, sugere a cliente e mostra uma **tela de conferência**. Nada é salvo antes de você confirmar. Nota já cadastrada (pela chave ou pelo número + sistema) é ignorada.

**Nova nota manual:** número, cliente, valor bruto, valor líquido, data de emissão, competência e, se quiser, **lançar o ISS** (cria a despesa pendente com vencimento no dia 20 do mês seguinte).

**Baixa do ISS:** selecione as notas e escolha **lançar (a pagar)** ou **dar baixa (pago)**. Se a despesa ainda não existir, ela é criada.

**Anular nota:** a nota fica **anulada** (o registro é mantido) e o ISS pendente dela é cancelado. Se o ISS já foi pago, a anulação é bloqueada: combine o tratamento com a contabilidade.

### 7.3 Possíveis duplicidades
O quadro **Possíveis duplicidades** aponta notas que podem ter sido lançadas duas vezes:
- **provável duplicidade:** mesma cliente, mesmo sistema e mesmo valor;
- **conferir:** mesma ficha com valor ou sistema diferente (pode ser serviço adicional ou nota reemitida);
- **mesmo nome, outra ficha:** pode ser outro filho (outra gestação).

Para cada caso, escolha uma decisão:
- **Não é duplicidade**, com o motivo (serviço adicional, outro filho, nota reemitida com a anterior tratada, outro motivo). O grupo vai para "Já revisadas" e pode ser reaberto.
- **É duplicidade:** indique qual nota é a repetida. Ela vai para "Duplicidades confirmadas — a tratar", com o botão **Anular esta nota** (se o ISS ainda não foi pago).

Decidir não altera nenhum valor; só **Anular** muda dados.

### 7.4 ISS do Mês
Escolha o **mês e o ano de emissão**: mostra as notas emitidas, o ISS de cada uma, o resumo mês a mês e o **vencimento da guia**. Tem **Imprimir** e exportar em **CSV**. É a tela que a contabilidade usa.

### 7.5 Contratos × ISS (Gerência)
Cruza os contratos com as notas e o ISS: mostra clientes com contrato pago **sem nota**, valor do contrato, valor da nota, ISS e situação. Filtros de período e de situação do ISS; tem **Imprimir / PDF**.

---

## 8. Relatórios financeiros

- **DRE:** resultado por centro de custo, no regime de **competência** ou de **caixa**, no período escolhido.
- **Fluxo de Caixa:** movimentação real por dia (entradas, saídas, saldo do dia e saldo acumulado), com clique no dia para ver os detalhes, e **previsão** de recebimentos e de pagamentos pendentes. Filtros de datas e forma de pagamento.
- **Caixa da Empresa:** por mês do parto: entradas líquidas, repasses às prestadoras, o que **fica na empresa**, despesas pagas e o **resultado**.
- **Relatório Gerencial:** relatório do mês (ou período) por tipo e escopo, com saldo real disponível, composição do ISS, receitas por categoria, despesas por centro de custo e pagamento por prestadora. Tem **Imprimir / PDF**.

---

## 9. Folha de pagamento e repasse às prestadoras

### 9.1 Como o repasse funciona
1. O **lucro bruto do mês** é o que entra pelos **contratos dos partos do mês** (valor líquido, já sem taxa de cartão), mais atendimentos avulsos.
2. Esse valor é **rateado entre as prestadoras pelas horas** da escala. A hora **noturna vale 1,25 vez** a diurna; horas extras entram no cálculo.
3. As **despesas do mês** são rateadas entre elas (regra abaixo), e o que sobra é o **repasse**.

**Despesas do mês:** não há desconto individual em %. As despesas são **somadas e rateadas** na proporção do valor bruto de cada prestadora, com o **mesmo percentual para todas**. Entram:
- as despesas pagas no mês (exceto taxa de cartão, repasses e a própria Folha);
- o **ISS das notas emitidas no mês** (pago ou ainda a pagar). O pagamento do ISS sai do caixa no mês seguinte, mas o desconto das prestadoras é no mês da **emissão**;
- a despesa **em % do lucro bruto**, como a Administração (calculada sobre o lucro bruto da Folha).

Algumas despesas podem ser marcadas pela administração como **fora do rateio** (por exemplo, o ISS de notas atrasadas). Elas saem do caixa, mas não são descontadas das prestadoras.

Se a sua empresa preferir o modelo antigo, com desconto individual em % por prestadora, defina a data de início do rateio em `marca.json` (`rateio_custos_desde`); os meses anteriores a ela usam o desconto individual cadastrado em cada prestadora.

### 9.2 Montar a Folha do mês
1. **Folha de Pagamento > Nova Folha:** escolha **mês e ano**. Entram as prestadoras ativas.
2. **Escala:** informe, para cada prestadora, as **horas diurnas, noturnas, extras diurnas e extras noturnas**. Salve a escala.
3. **Receitas:** inclua os contratos do mês:
   - **Importar parto:** a lista mostra as clientes que tiveram parto no mês e ainda não estão na Folha; importe cada uma (o valor sugerido é o líquido do contrato).
   - **Importar atendimento:** atendimentos realizados com valor (se foi "somente uma prestadora", a receita fica só com ela).
   - **Nova receita:** lançamento manual.
   - **Sincronizar receitas:** refaz os valores a partir dos lançamentos atuais da cliente, caso um contrato tenha sido corrigido depois de importado.
   - **Excluir receita:** remove uma receita da Folha (só com a Folha aberta).
4. Confira o **resultado**: bruto, despesas rateadas e líquido (repasse) de cada prestadora.
5. **Reservar previsão** (opcional): cria uma despesa pendente com o total estimado do repasse, para aparecer no fluxo de caixa.
6. **Relatório da Folha:** versão para imprimir.

### 9.3 Fechar a Folha
**Registrar pagamentos** fecha a Folha. O sistema:
- lança como **paga** a despesa em % do lucro bruto (Administração) no último dia do mês, sobre o lucro bruto da Folha;
- **grava o total de despesas rateadas**, para o repasse pago não mudar depois;
- cria **uma despesa paga por prestadora** com o valor líquido (por padrão, data de pagamento no **1º dia do mês seguinte**; dá para escolher a data e a forma).

Depois de fechada, a Folha **não muda mais**. Um parto registrado depois do fechamento entra como **complemento na folha do mês seguinte**.

**Antes de fechar:** importe todos os partos do mês, confira horas e receitas e deixe a Administração **pendente** (não pague nem cancele).

### 9.4 Prestadoras (cadastro)
**Folha de Pagamento > Prestadores de serviço:** nome, CPF, cargo/função, taxa de desconto (só vale nos meses anteriores ao início do rateio) e **ativo**. Quem for inativada depois de a Folha ser criada, se não tiver horas nem receita direcionada naquele mês, sai da Folha aberta; se trabalhou no mês, continua.

### 9.5 Relatório de Faturamento e demonstrativo
- **Administração:** o relatório mostra, para o mês, as entradas, o lucro bruto, o repasse de cada prestadora, o **descritivo das despesas rateadas** e o demonstrativo individual. Com a Folha **aberta**, aparece o aviso **PRÉVIA**: os valores podem mudar até o fechamento.
- **Prestadora:** vê o **demonstrativo do próprio repasse** (base de cálculo, horas, valor bruto, "Despesas mensais" e a parte dela em cada grupo de despesa). Quando a Folha ainda está aberta, o demonstrativo fica indisponível.

---

## 10. Notas fiscais das prestadoras

O repasse é pago **mediante nota fiscal** que a prestadora emite para a empresa.

**Prestadora ("Minhas Notas Fiscais"):**
1. Escolha o **mês do repasse**; o sistema mostra o valor exato do repasse.
2. Emita a nota **exatamente com esse valor** e envie o **XML**.
3. O sistema confere o valor e informa a situação. Se não bater, emita de novo com o valor correto.
4. Só é possível enviar a nota de um mês com a **Folha fechada**.

**Administração ("Notas das Prestadoras"):**
1. Escolha o mês e veja, por prestadora: repasse a pagar, nota, valor da nota e situação.
2. As notas **conferidas** (valor igual ao repasse) podem ser pagas. O total a pagar aparece no alto.
3. **Registrar pagamento** marca como pago; **Desfazer** reverte.

---

## 11. Gerência

- **Relatório Gerencial, Contratos × ISS, Caixa da Empresa:** ver o capítulo 8 e a seção 7.5.
- **Formas de Pagamento:**
  - cadastre ou **bloqueie** formas (um bloqueio não apaga o histórico; os lançamentos antigos continuam com o nome);
  - em **Operadoras e taxas**, cadastre as operadoras (maquininhas e link de pagamento), as **parcelas máximas** e a **taxa (%)** de cada modalidade. As taxas começam em 0,00%: preencha em seguida. Esses percentuais calculam a taxa de cartão automática.
- **Conta Bancária:**
  1. **Cadastre as contas** (só o nome: por exemplo Itaú, Nubank, Caixa).
  2. **Registre o saldo** do extrato de cada conta, com data e valor.
  3. A tela mostra o **total nas contas** (soma do último saldo de cada conta), o **saldo em caixa do sistema** e a **diferença**. O caixa do sistema começa no primeiro lançamento, então a diferença inclui o que já havia nas contas antes. O que importa é se a diferença **muda** de uma conferência para a outra: isso indica algo que entrou ou saiu do banco sem passar pelo sistema (ou ao contrário).
  4. O histórico mostra a **variação** de cada conta entre os registros. Uma conta só pode ser excluída se não tiver saldos.

---

## 12. Administração de usuários

**Usuários e Permissões** (só a administradora):
- **Novo usuário:** nome, e-mail (é o usuário de acesso), perfil, e, se for prestadora, a **prestadora vinculada**. A senha inicial deve ser informada **por um meio seguro**; a pessoa troca depois no ícone de chave.
- **Perfis:** Administradora (tudo), Prestadora de serviço (áreas marcadas, o próprio repasse e as próprias notas) e Contabilidade (consulta de repasses e ISS).
- **Áreas:** marque o que cada pessoa pode acessar. Há **Marcar tudo** e **Limpar**.
- **Ativar/desativar** um usuário sem apagar.

**Esconder o repasse das prestadoras (opcional):** em `permissoes.py`, a chave `OCULTAR_REPASSE_DAS_PRESTADORAS = True` esconde das prestadoras a Folha e o demonstrativo de repasse, por exemplo enquanto a administração ajusta valores. Elas continuam vendo "Minhas Notas Fiscais". A administração e a contabilidade não são afetadas.

---

## 13. Como corrigir um erro

| Situação | O que fazer |
|---|---|
| Dei **baixa** em uma despesa por engano | Abra a despesa (lápis) e clique em **Desfazer pagamento**. Ela volta para pendente em Contas a Pagar. Não vale para despesas da Folha nem taxas de cartão. |
| Recebi no valor ou na data errada | Receitas recebidas não têm o botão de desfazer: avise a administração do sistema. |
| Lancei uma **nota em duplicidade** | Use o quadro **Possíveis duplicidades** e **Anular esta nota** (se o ISS ainda não foi pago). |
| Importei um **contrato com valor errado** na Folha | Corrija o lançamento da cliente e use **Sincronizar receitas** (Folha aberta). |
| Registrei o **parto na data errada** | Corrija a data na ficha da cliente (campo "Data do parto") e confira a competência dos lançamentos do contrato; se algo não acompanhar, fale com quem administra o sistema. |
| Um **atendimento** foi lançado por engano | **Cancelar** (mantém o registro) ou **Excluir** (apaga também os lançamentos). |
| A **Folha já foi fechada** e algo mudou | A Folha fechada não muda. Parto novo entra como complemento da folha seguinte; fale com a administração do sistema para outros casos. |

---

## 14. Rotina sugerida

**No dia a dia**
- Registrar os **atendimentos** realizados e os **recebimentos** (Contas a Receber).
- **Registrar o parto** assim que acontecer.
- Lançar e pagar as **despesas** (Contas a Pagar).

**Quando uma nota é emitida**
- Importar o **XML** na tela Nota Fiscal e conferir; o ISS fica a pagar para o dia 20 do mês seguinte.

**Todo dia 20**
- Pagar o **ISS** do mês anterior em Contas a Pagar.

**No fim do mês**
1. Conferir que todos os **partos do mês** estão registrados.
2. Montar a **Folha**: escala, importar os partos e conferir o resultado.
3. Deixar a **Administração** pendente e **fechar a Folha**.
4. Conferir o **Relatório de Faturamento** e os repasses.
5. As prestadoras enviam as **notas**; a administração confere e registra o pagamento.
6. Registrar o **saldo das contas bancárias** em Gerência > Conta Bancária.

**Todo mês**
- Olhar o quadro de **possíveis duplicidades** e o **ISS do Mês**.

---

## 15. Glossário

- **DPP:** data prevista do parto.
- **EO:** enfermeira obstetra.
- **Competência:** o mês a que o lançamento pertence (não é, necessariamente, o mês em que o dinheiro entrou).
- **Regime de caixa:** conta o dinheiro na data em que entrou ou saiu.
- **Lucro bruto da Folha:** soma das receitas (contratos e atendimentos) incluídas na Folha do mês.
- **Rateio:** divisão proporcional (das receitas pelas horas e das despesas pelo valor bruto de cada prestadora).
- **Repasse:** valor líquido que a prestadora recebe no mês.
- **Folha aberta / fechada:** aberta ainda aceita alterações; fechada já gerou os pagamentos e não muda.
- **ISS:** imposto sobre serviços (6% do valor da nota), pago no dia 20 do mês seguinte à emissão.
- **Nota municipal / nacional:** sistemas de emissão de nota (até 2025 e de 2026 em diante, conforme a prefeitura).
- **Despesa recorrente:** despesa que se repete todo mês.
- **Lançamento liquidado:** já recebido ou pago; só descrição, observações e centro de custo podem ser alterados.

---

## 16. Cuidados

- **Dados das clientes são sigilosos.** Não compartilhe a tela, os relatórios nem os XMLs das notas (eles trazem CPF).
- **Não divida a senha.** Cada pessoa tem o seu acesso.
- Em caso de dúvida antes de **fechar a Folha**, **pagar** em lote ou **anular** uma nota, confira com quem administra o sistema.
- O sistema faz **cópia de segurança** do banco antes de alterações em lote feitas por script; para outros casos, peça a quem administra.
