# human-requests-bot

Простой бот для CI/CD GitHub пайплайна который создает issue при падении теста и загружает изображение браузера в артифакт (требуется human_requests)

Использование:
```yml
      - name: Run tests (venv)
        run: |
          set -o pipefail
          venv/bin/python -m pytest --tb=short 2>&1 | tee error.log
        
      - name: report playwright failure
        if: failure()
        uses: Miskler/human-requests-bot@v8
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          log_path: error.log
          screenshot_path: screenshot.png
```
* Важно чтобы pytest сохранил лог как файл
