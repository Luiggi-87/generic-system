/**
 * taxas.js — Calculadora de taxas das operadoras de cartão (Sistema de Gestão)
 */

// Tabela vigente vem do banco (base.html define window.TAXAS_DB); abaixo, valores de reserva.
const TAXAS = window.TAXAS_DB || {
  tom: {
    debito: 1.39,
    credito: {
      1: 3.34, 2: 7.29, 3: 8.35, 4: 9.23, 5: 10.10,
      6: 10.85, 7: 10.90, 8: 10.95, 9: 11.00, 10: 11.05,
      11: 11.73, 12: 12.38, 13: 13.02, 14: 13.66, 15: 14.30,
      16: 14.94, 17: 15.58, 18: 16.22
    }
  },
  infinite: {
    debito: 1.37,
    credito: {
      1: 3.15, 2: 5.39, 3: 6.12, 4: 6.85, 5: 7.57,
      6: 8.28, 7: 8.99, 8: 9.69, 9: 10.38, 10: 11.06,
      11: 11.74, 12: 12.40
    }
  }
};

// Como cada forma calcula taxa: 'nenhuma' | 'debito' | 'credito' (definido na tela Formas de Pagamento)
const FORMAS_TAXA = window.FORMAS_TAXA ||
  { cartao_debito: 'debito', cartao_credito: 'credito', link_pagamento: 'credito' };
const OPERADORAS_NOMES = window.OPERADORAS_NOMES || { tom: 'Tom', infinite: 'Infinite Pay' };

function tipoTaxa(forma) { return FORMAS_TAXA[forma] || 'nenhuma'; }
function nomeOperadora(cod) { return OPERADORAS_NOMES[cod] || cod; }

function getTaxaPct(forma, parcelas, operadora) {
  const op = TAXAS[operadora] || TAXAS.tom;
  const tipo = tipoTaxa(forma);
  if (tipo === 'debito') return op.debito;
  if (tipo === 'credito') {
    const p = Math.max(1, parseInt(parcelas) || 1);
    const maxP = Math.max(...Object.keys(op.credito).map(Number));
    return op.credito[Math.min(p, maxP)] || op.credito[1];
  }
  return 0;
}

function brl(v) {
  return 'R$ ' + Math.abs(v).toLocaleString('pt-BR', { minimumFractionDigits: 2 });
}

/**
 * Ativa o cálculo de taxa em um modal de pagamento.
 * Reconhece automaticamente seletor [name="operadora"] se presente no modal.
 */
function initTaxaModal(modalEl, valorBruto) {
  const selForma     = modalEl.querySelector('[name="forma_pagamento"]');
  const selParcelas  = modalEl.querySelector('[name="parcelas"]');
  const selOperadora = modalEl.querySelector('[name="operadora"]');
  const divParcelas  = modalEl.querySelector('.div-parcelas');
  const divOperadora = modalEl.querySelector('.div-operadora');
  const divInfo      = modalEl.querySelector('.taxa-info');
  if (!selForma || !divInfo) return;

  function atualizar() {
    const forma     = selForma.value;
    const parcelas  = selParcelas ? parseInt(selParcelas.value) || 1 : 1;
    const operadora = selOperadora ? selOperadora.value : 'infinite';
    const taxaPct   = getTaxaPct(forma, parcelas, operadora);
    const taxaVal   = Math.round(valorBruto * taxaPct) / 100;
    const liquido   = Math.round((valorBruto - taxaVal) * 100) / 100;
    const isCartao  = tipoTaxa(forma) !== 'nenhuma';
    const nomeOp    = nomeOperadora(operadora);

    if (divOperadora) divOperadora.style.display = isCartao ? 'block' : 'none';
    if (divParcelas)  divParcelas.style.display  = tipoTaxa(forma) === 'credito' ? 'block' : 'none';

    if (taxaPct > 0) {
      divInfo.innerHTML =
        `<div class="d-flex justify-content-between">
           <span><i class="bi bi-info-circle me-1"></i>Taxa ${nomeOp} (${taxaPct.toFixed(2).replace('.', ',')}%):</span>
           <strong class="text-danger">− ${brl(taxaVal)}</strong>
         </div>
         <div class="d-flex justify-content-between border-top pt-1 mt-1">
           <span class="fw-bold">Valor líquido (entra na conta):</span>
           <strong class="text-success">${brl(liquido)}</strong>
         </div>`;
    } else {
      divInfo.innerHTML =
        `<div class="d-flex justify-content-between align-items-center">
           <span><i class="bi bi-check-circle-fill text-success me-1"></i>Sem taxa — valor integral entra na conta</span>
           <strong class="text-success">${brl(valorBruto)}</strong>
         </div>`;
    }
    divInfo.style.display = 'block';
  }

  selForma.addEventListener('change', atualizar);
  if (selParcelas)  selParcelas.addEventListener('change', atualizar);
  if (selOperadora) selOperadora.addEventListener('change', atualizar);
  atualizar();
}

// Auto-inicializa quando o Bootstrap abre um modal
document.addEventListener('show.bs.modal', function (e) {
  const modal = e.target;
  const valorStr = modal.getAttribute('data-valor');
  if (valorStr) {
    initTaxaModal(modal, parseFloat(valorStr));
  }
});
