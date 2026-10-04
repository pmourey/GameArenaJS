#!/bin/bash
# Script de redémarrage du serveur Flask

echo "🛑 Arrêt de Flask sur le port 5000..."
lsof -ti:5000 | xargs kill -9 2>/dev/null

sleep 1

if lsof -ti:5000 > /dev/null 2>&1; then
    echo "❌ Le port 5000 est toujours utilisé"
    exit 1
fi

echo "✅ Port 5000 libéré"
echo ""
echo "🚀 Démarrage du serveur Flask..."
echo "   URL: http://127.0.0.1:5000"
echo "   Logs: Affichés ci-dessous"
echo "   Arrêter: Ctrl+C"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /Users/display/PycharmProjects/GameArena
python3 app.py
