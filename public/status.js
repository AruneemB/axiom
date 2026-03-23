(async function () {
  const el = document.getElementById('status');
  const text = document.getElementById('status-text');
  const stats = document.getElementById('stats');
  const ticker = document.getElementById('ticker');

  const topics = [
    "alpha generation",
    "alpha signals",
    "arbitrage free modeling",
    "clustering financial data",
    "contrastive learning",
    "controlled differential equation",
    "derivatives pricing",
    "diffusion models",
    "financial time series",
    "fractional brownian motion",
    "game theory finance",
    "generative models time series",
    "hidden markov models",
    "implied volatility",
    "information geometry",
    "latent variable models",
    "limit order book",
    "local volatility",
    "manifold learning",
    "market microstructure",
    "neural cde",
    "neural sde",
    "optimal execution",
    "optimal transport finance",
    "options pricing",
    "quantitative finance theory",
    "regime detection",
    "reinforcement learning trading",
    "representation learning",
    "rough volatility",
    "score based models",
    "self supervised learning",
    "sequence modeling",
    "state space models",
    "statistical arbitrage",
    "stochastic control",
    "stochastic differential equation",
    "stochastic volatility",
    "term structure modeling",
    "time series representation learning",
    "transformer time series",
    "vix",
    "volatility indices",
    "volatility surface",
    "vvix",
    "vxn"
  ];

  // Populate ticker twice for seamless scrolling
  if (ticker) {
    const content = topics.map(t => `<span>${t}</span>`).join('');
    ticker.innerHTML = content + content;
  }

  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    if (d.status === 'active') {
      el.className = 'status active';
      text.textContent = 'Active';
      document.getElementById('papers').textContent = d.total_papers.toLocaleString();
      document.getElementById('ideas').textContent = d.total_ideas.toLocaleString();
      stats.classList.add('visible');
    } else {
      throw new Error();
    }
  } catch {
    el.className = 'status error';
    text.textContent = 'Unreachable';
  }
})();
