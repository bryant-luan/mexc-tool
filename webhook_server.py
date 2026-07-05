from flask import Flask, request, jsonify
import json

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Gate.io 持倉更新:", json.dumps(data, indent=2))
    return jsonify({"status": "success"})

if __name__ == '__main__':
    print("Webhook 伺服器運行中...")
    app.run(host='0.0.0.0', port=5000, debug=True)