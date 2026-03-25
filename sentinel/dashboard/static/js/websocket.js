/* WebSocket handler for live research cycle updates */

const WS = {
    _socket: null,
    _callbacks: [],

    connect(cycleId) {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${location.host}/ws/research/${cycleId}`;
        this._socket = new WebSocket(url);

        this._socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this._callbacks.forEach(cb => cb(data));
        };

        this._socket.onclose = () => {
            this._socket = null;
        };
    },

    disconnect() {
        if (this._socket) {
            this._socket.close();
            this._socket = null;
        }
        this._callbacks = [];
    },

    onUpdate(callback) {
        this._callbacks.push(callback);
    },

    ping() {
        if (this._socket && this._socket.readyState === WebSocket.OPEN) {
            this._socket.send('ping');
        }
    },
};
