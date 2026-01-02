<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Real-Time Stock Charting Software</title>
    <style>
        :root {
            --bg-color: #131722;
            --panel-color: #1e222d;
            --text-color: #d1d4dc;
            --border-color: #363a45;
            --accent-color: #2962ff;
            --up-color: #26a69a;
            --down-color: #ef5350;
            --grid-color: #2a2e39;
        }

        body {
            margin: 0;
            padding: 0;
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }

        header {
            padding: 1rem 1.5rem;
            background-color: var(--panel-color);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .brand {
            font-size: 1.25rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .brand span { color: var(--accent-color); }

        .controls {
            display: flex;
            gap: 0.75rem;
        }

        input {
            background: #2a2e39;
            border: 1px solid var(--border-color);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            font-size: 0.9rem;
            outline: none;
            text-transform: uppercase;
            width: 120px;
        }

        input:focus { border-color: var(--accent-color); }

        button {
            background: var(--accent-color);
            color: white;
            border: none;
            padding: 0.5rem 1.25rem;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9rem;
            transition: opacity 0.2s;
        }

        button:hover { opacity: 0.9; }
        button:active { transform: translateY(1px); }

        main {
            flex: 1;
            position: relative;
            display: flex;
            flex-direction: column;
        }

        #chart-container {
            flex: 1;
            position: relative;
            overflow: hidden;
            cursor: crosshair;
        }

        canvas { display: block; width: 100%; height: 100%; }

        .tooltip {
            position: absolute;
            background: rgba(30, 34, 45, 0.95);
            border: 1px solid var(--border-color);
            padding: 10px;
            border-radius: 6px;
            pointer-events: none;
            display: none;
            font-size: 0.85rem;
            z-index: 10;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            min-width: 140px;
        }

        .tooltip-row {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 2px;
        }
        .tooltip-row.header {
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 4px;
            margin-bottom: 6px;
            font-weight: bold;
            color: var(--accent-color);
        }

        .status-bar {
            padding: 0.5rem 1.5rem;
            background: var(--panel-color);
            border-top: 1px solid var(--border-color);
            font-size: 0.9rem;
            display: flex;
            gap: 2rem;
            align-items: center;
            height: 40px;
        }

        .stat {
            display: flex;
            align-items: baseline;
            gap: 0.5rem;
        }

        .stat-label { color: #787b86; }
        .stat-value { font-weight: 600; font-variant-numeric: tabular-nums; }
        
        .up { color: var(--up-color); }
        .down { color: var(--down-color); }

        .loader {
            position: absolute;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            color: var(--accent-color);
            font-size: 1.2rem;
            font-weight: 600;
            display: none;
        }
    </style>
</head>
<body>
    <header>
        <div class="brand">
            StockChart<span>Pro</span>
        </div>
        <div class="controls">
            <input type="text" id="symbol-input" value="AAPL" placeholder="Symbol">
            <button id="load-btn">Load Data</button>
        </div>
    </header>

    <main>
        <div id="chart-container">
            <div id="loader" class="loader">Loading Market Data...</div>
            <canvas id="stockCanvas"></canvas>
            <div id="tooltip" class="tooltip"></div>
        </div>

        <div class="status-bar">
            <div class="stat">
                <span class="stat-label">Price:</span>
                <span id="price" class="stat-value">-</span>
            </div>
            <div class="stat">
                <span class="stat-label">Change:</span>
                <span id="change" class="stat-value">-</span>
            </div>
            <div class="stat">
                <span class="stat-label">Volume:</span>
                <span id="volume" class="stat-value">-</span>
            </div>
            <div class="stat">
                <span class="stat-label">High:</span>
                <span id="high" class="stat-value">-</span>
            </div>
            <div class="stat">
                <span class="stat-label">Low:</span>
                <span id="low" class="stat-value">-</span>
            </div>
        </div>
    </main>

    <script>
        /**
         * =========================================================================
         * REPOSITORY LAYER (Ported to Client-Side)
         * Corresponds to: src/data/repositories/istock_repository.py
         * 
         * This class replaces the Python-based repository with a JavaScript 
         * implementation capable of fetching real-time data from Yahoo Finance 
         * directly in the browser, fulfilling the "Real Data" requirement.
         * =========================================================================
         */
        class StockRepository {
            constructor() {
                // Using corsproxy.io to bypass CORS restrictions inherent in browser-based Yahoo API calls.
                // This allows fetching data without a dedicated backend proxy.
                this.proxyUrl = 'https://corsproxy.io/?';
            }

            /**
             * Fetches intraday data for a given symbol.
             * 
             * @param {string} symbol - The stock ticker (e.g., 'AAPL')
             * @param {string} interval - Time interval ('1m', '5m', '15m', '1h')
             * @param {string} range - Date range ('1d', '5d', '1mo')
             * @returns {Promise<Array>} Array of objects containing {date, open, high, low, close, volume}
             */
            async getIntradayData(symbol, interval = '1m', range = '1d') {
                // Construct the Yahoo Finance API v8 URL
                const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=${interval}&range=${range}`;
                const encodedUrl = encodeURIComponent(targetUrl);
                const requestUrl = this.proxyUrl + encodedUrl;

                try {
                    const response = await fetch(requestUrl);
                    
                    if (!response.ok) {
                        throw new Error(`HTTP Error: ${response.status}`);
                    }

                    const json = await response.json();
                    
                    // Validate response structure
                    const result = json.chart?.result?.[0];
                    if (!result) {
                        console.warn("No result found for symbol:", symbol);
                        throw new Error('Invalid symbol or no data available');
                    }

                    const quote = result.indicators?.quote?.[0];
                    const timestamp = result.timestamp;
                    
                    if (!quote || !timestamp) return [];

                    // Map Yahoo's response format to our application's data model
                    return timestamp.map((ts, index) => {
                        const open = quote.open[index];
                        const high = quote.high[index];
                        const low = quote.low[index];
                        const close = quote.close[index];
                        const volume = quote.volume[index];

                        // Handle market gaps (nulls)
                        if (open === null) return null;

                        return {
                            date: new Date(ts * 1000),
                            open,
                            high,
                            low,
                            close,
                            volume
                        };
                    }).filter(d => d !== null); // Filter out null gaps

                } catch (error) {
                    console.error('StockRepository Fetch Error:', error);
                    throw error;
                }
            }
        }

        /**
         * =========================================================================
         * CHARTING & UI LOGIC
         * Handles rendering the data to the HTML5 Canvas.
         * =========================================================================
         */
        class StockChartApp {
            constructor() {
                this.repository = new StockRepository();
                this.canvas = document.getElementById('stockCanvas');
                this.ctx = this.canvas.getContext('2d', { alpha: false }); // Optimize for no transparency
                this.container = document.getElementById('chart-container');
                this.tooltip = document.getElementById('tooltip');
                this.loader = document.getElementById('loader');
                
                this.data = [];
                this.symbol = 'AAPL';
                
                // Layout configuration
                this.margin = { top: 20, right: 60, bottom: 30, left: 10 };
                
                this.initListeners();
                this.resize();
                this.loadData();
                
                window.addEventListener('resize', () => {
                    this.resize();
                    this.draw();
                });
            }

            initListeners() {
                const loadBtn = document.getElementById('load-btn');
                const symbolInput = document.getElementById('symbol-input');

                const triggerLoad = () => {
                    const val = symbolInput.value.toUpperCase().trim();
                    if(val) {
                        this.symbol = val;
                        this.loadData();
                    }
                };

                loadBtn.addEventListener('click', triggerLoad);
                symbolInput.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter') triggerLoad();
                });

                this.canvas.addEventListener('mousemove', (e) => this.handleMouseMove(e));
                this.canvas.addEventListener('mouseleave', () => {
                    this.tooltip.style.display = 'none';
                    this.draw(); // Redraw to clear crosshair
                });
            }

            async loadData() {
                this.setLoading(true);
                try {
                    // Fetch 1-minute interval data for the last 1 day (up to current minute)
                    this.data = await this.repository.getIntradayData(this.symbol, '1m', '1d');
                    
                    if (this.data.length === 0) {
                        alert(`No data found for ${this.symbol}. Check symbol or try again later.`);
                    } else {
                        this.updateStatusBar();
                        this.draw();
                    }
                } catch (e) {
                    alert('Failed to fetch data. ' + e.message);
                } finally {
                    this.setLoading(false);
                }
            }

            setLoading(isLoading) {
                this.loader.style.display = isLoading ? 'block' : 'none';
                if (isLoading) {
                    // Clear canvas visually while loading
                    this.ctx.fillStyle = '#131722';
                    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
                }
            }

            updateStatusBar() {
                if (this.data.length === 0) return;

                const last = this.data[this.data.length - 1];
                const first = this.data[0]; // Using day open as baseline
                
                const change = last.close - first.open;
                const percent = first.open !== 0 ? (change / first.open) * 100 : 0;
                
                const colorClass = change >= 0 ? 'up' : 'down';
                const sign = change >= 0 ? '+' : '';

                const formatNum = (n) => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

                document.getElementById('price').innerHTML = `<span class="${colorClass}">${formatNum(last.close)}</span>`;
                document.getElementById('change').innerHTML = `<span class="${colorClass}">${sign}${formatNum(change)} (${sign}${percent.toFixed(2)}%)</span>`;
                document.getElementById('volume').textContent = last.volume.toLocaleString();
                document.getElementById('high').innerHTML = `<span class="${colorClass}">${formatNum(last.high)}</span>`;
                document.getElementById('low').innerHTML = `<span class="${colorClass}">${formatNum(last.low)}</span>`;
            }

            resize() {
                const rect = this.container.getBoundingClientRect();
                this.canvas.width = rect.width;
                this.canvas.height = rect.height;
                // High DPI scaling could be added here for retina displays
            }

            /**
             * Calculates scaling factors based on current data and canvas size.
             */
            getScales() {
                if (this.data.length === 0) return null;

                const width = this.canvas.width - this.margin.left - this.margin.right;
                const height = this.canvas.height - this.margin.top - this.margin.bottom;

                // Determine Min/Max Price
                let minPrice = Infinity;
                let maxPrice = -Infinity;
                let maxVol = 0;

                this.data.forEach(d => {
                    if (d.low < minPrice) minPrice = d.low;
                    if (d.high > maxPrice) maxPrice = d.high;
                    if (d.volume > maxVol) maxVol = d.volume;
                });

                // Add vertical padding (10%) so candles aren't touching edges
                const pricePadding = (maxPrice - minPrice) * 0.1;
                if (pricePadding === 0) { // Handle flat line
                    minPrice -= 1;
                    maxPrice += 1;
                } else {
                    minPrice -= pricePadding;
                    maxPrice += pricePadding;
                }

                // Scale functions
                const xScale = (index) => this.margin.left + (index / (this.data.length - 1)) * width;
                const yScale = (price) => this.margin.top + height - ((price - minPrice) / (maxPrice - minPrice)) * height;

                return { width, height, minPrice, maxPrice, maxVol, xScale, yScale };
            }

            draw(crosshairIndex = -1) {
                if (this.data.length === 0) return;

                const { width, height, minPrice, maxPrice, maxVol, xScale, yScale } = this.getScales();
                const ctx = this.ctx;

                // 1. Clear Background
                ctx.fillStyle = '#131722';
                ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

                const candleWidth = width / this.data.length;

                // 2. Draw Grid Lines
                ctx.strokeStyle = '#2a2e39';
                ctx.lineWidth = 1;
                ctx.font = '10px Arial';
                ctx.textAlign = 'left';
                ctx.fillStyle = '#787b86';

                // Horizontal Price Grid (5 lines)
                for (let i = 0; i <= 5; i++) {
                    const priceVal = minPrice + (maxPrice - minPrice) * (i / 5);
                    const yPos = yScale(priceVal);
                    
                    ctx.beginPath();
                    ctx.moveTo(this.margin.left, yPos);
                    ctx.lineTo(this.canvas.width - this.margin.right, yPos);
                    ctx.stroke();

                    // Price Label
                    ctx.fillText(priceVal.toFixed(2), this.canvas.width - this.margin.right + 5, yPos + 3);
                }

                // 3. Draw Volume Bars (Bottom 20% of chart)
                const volHeight = height * 0.2;
                const volBase = this.canvas.height - this.margin.bottom;
                
                this.data.forEach((d, i) => {
                    const x = xScale(i);
                    const barHeight = (d.volume / maxVol) * volHeight;
                    const isUp = d.close >= d.open;
                    
                    ctx.fillStyle = isUp ? 'rgba(38, 166, 154, 0.15)' : 'rgba(239, 83, 80, 0.15)';
                    ctx.fillRect(x - candleWidth/2, volBase - barHeight, candleWidth, barHeight);
                });

                // 4. Draw Candlesticks
                this.data.forEach((d, i) => {
                    const x = xScale(i);
                    const yOpen = yScale(d.open);
                    const yClose = yScale(d.close);
                    const yHigh = yScale(d.high);
                    const yLow = yScale(d.low);
                    
                    const isUp = d.close >= d.open;
                    const color = isUp ? '#26a69a' : '#ef5350';

                    ctx.strokeStyle = color;
                    ctx.fillStyle = color;
                    ctx.lineWidth = 1;

                    // Wick (High to Low)
                    ctx.beginPath();
                    ctx.moveTo(x, yHigh);
                    ctx.lineTo(x, yLow);
                    ctx.stroke();

                    // Body (Open to Close)
                    let bodyHeight = Math.abs(yClose - yOpen);
                    if (bodyHeight < 1) bodyHeight = 1; // Ensure visibility of small movements
                    
                    // Rect coordinates: x, y, w, h
                    ctx.fillRect(
                        x - candleWidth/2 + 0.5, 
                        Math.min(yOpen, yClose), 
                        Math.max(1, candleWidth - 1), 
                        bodyHeight
                    );
                });

                // 5. Draw Crosshair if requested
                if (crosshairIndex >= 0 && crosshairIndex < this.data.length) {
                    const d = this.data[crosshairIndex];
                    const x = xScale(crosshairIndex);
                    const y = yScale(d.close);

                    ctx.save();
                    ctx.setLineDash([6, 6]);
                    ctx.strokeStyle = '#787b86';
                    ctx.lineWidth = 1;

                    // Vertical Line
                    ctx.beginPath();
                    ctx.moveTo(x, 0);
                    ctx.lineTo(x, this.canvas.height);
                    ctx.stroke();

                    // Horizontal Line
                    ctx.beginPath();
                    ctx.moveTo(0, y);
                    ctx.lineTo(this.canvas.width, y);
                    ctx.stroke();
                    
                    // Price Label Bubble on Y Axis
                    const priceText = d.close.toFixed(2);
                    ctx.fillStyle = '#363a45';
                    ctx.fillRect(this.canvas.width - 55, y - 10, 50, 20);
                    ctx.fillStyle = '#fff';
                    ctx.fillText(priceText, this.canvas.width - 50, y + 4);

                    // Time Label Bubble on X Axis
                    const timeText = d.date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    const timeWidth = ctx.measureText(timeText).width + 10;
                    ctx.fillStyle = '#363a45';
                    ctx.fillRect(x - timeWidth/2, this.canvas.height - 25, timeWidth, 20);
                    ctx.fillStyle = '#fff';
                    ctx.fillText(timeText, x - (timeWidth/2) + 5, this.canvas.height - 11);

                    ctx.restore();
                }
            }

            handleMouseMove(e) {
                if (this.data.length === 0) return;

                const rect = this.canvas.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                
                const { width, xScale } = this.getScales();
                
                // Inverse calculate index from MouseX
                let index = Math.round(((mouseX - this.margin.left) / width) * (this.data.length - 1));
                
                // Clamp index to valid range
                if (index < 0) index = 0;
                if (index >= this.data.length) index = this.data.length - 1;

                const d = this.data[index];

                // Redraw chart with crosshair
                this.draw(index);

                // Update and Position Tooltip
                this.tooltip.style.display = 'block';
                
                // Calculate position logic to keep tooltip on screen
                const tooltipX = e.clientX + 15;
                const tooltipY = e.clientY + 15;
                
                this.tooltip.style.left = tooltipX + 'px';
                this.tooltip.style.top = tooltipY + 'px';

                const format = (n) => n.toFixed(2);
                const isUp = d.close >= d.open;
                const color = isUp ? 'var(--up-color)' : 'var(--down-color)';

                this.tooltip.innerHTML = `
                    <div class="tooltip-row header" style="color:${color}">
                        <span>${this.symbol}</span>
                        <span>${d.date.toLocaleTimeString()}</span>
                    </div>
                    <div class="tooltip-row"><span>O:</span> <span>${format(d.open)}</span></div>
                    <div class="tooltip-row"><span>H:</span> <span>${format(d.high)}</span></div>
                    <div class="tooltip-row"><span>L:</span> <span>${format(d.low)}</span></div>
                    <div class="tooltip-row"><span>C:</span> <span>${format(d.close)}</span></div>
                    <div class="tooltip-row"><span>V:</span> <span>${d.volume.toLocaleString()}</span></div>
                `;
            }
        }

        // Initialize the application
        document.addEventListener('DOMContentLoaded', () => {
            const app = new StockChartApp();
        });
    </script>
</body>
</html>