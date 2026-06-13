{
  "builds": [
    {
      "src": "lume/wsgi.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/static/(.*)",
      "dest": "/static/$1"
    },
    {
      "src": "/(.*)",
      "dest": "lume/wsgi.py"
    }
  ]
}