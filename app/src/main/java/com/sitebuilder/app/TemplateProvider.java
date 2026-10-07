package com.sitebuilder.app;

public class TemplateProvider {

    public static final String[] NAMES = {
            "Лендинг", "Визитка", "Портфолио"
    };

    public static String getTemplate(int index) {
        switch (index) {
            case 0: return LANDING;
            case 1: return CARD;
            case 2: return PORTFOLIO;
            default: return LANDING;
        }
    }

    public static final String LANDING =
            "<!DOCTYPE html>\n" +
            "<html lang=\"ru\">\n" +
            "<head>\n" +
            "  <meta charset=\"utf-8\">\n" +
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
            "  <title>Лендинг</title>\n" +
            "  <style>\n" +
            "    body { font-family: sans-serif; margin: 0; padding: 40px; background: #efe6d2; color: #1b1a17; }\n" +
            "    h1 { font-size: 42px; }\n" +
            "    .btn { display: inline-block; background: #2340ff; color: #fff; padding: 14px 24px; text-decoration: none; border-radius: 8px; }\n" +
            "  </style>\n" +
            "</head>\n" +
            "<body>\n" +
            "  <h1>Заголовок</h1>\n" +
            "  <p>Описание вашего предложения.</p>\n" +
            "  <a class=\"btn\" href=\"#\">Оставить заявку</a>\n" +
            "</body>\n" +
            "</html>";

    public static final String CARD =
            "<!DOCTYPE html>\n" +
            "<html lang=\"ru\">\n" +
            "<head>\n" +
            "  <meta charset=\"utf-8\">\n" +
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
            "  <title>Визитка</title>\n" +
            "  <style>\n" +
            "    body { font-family: sans-serif; margin: 0; padding: 40px; background: #fff; color: #050505; }\n" +
            "    h1 { font-size: 32px; }\n" +
            "    ul { line-height: 1.8; }\n" +
            "  </style>\n" +
            "</head>\n" +
            "<body>\n" +
            "  <h1>Имя Фамилия</h1>\n" +
            "  <p>Веб-разработчик</p>\n" +
            "  <ul>\n" +
            "    <li>Сайты под ключ</li>\n" +
            "    <li>Дизайн и вёрстка</li>\n" +
            "    <li>Поддержка</li>\n" +
            "  </ul>\n" +
            "  <p>Email: mail@example.com</p>\n" +
            "</body>\n" +
            "</html>";

    public static final String PORTFOLIO =
            "<!DOCTYPE html>\n" +
            "<html lang=\"ru\">\n" +
            "<head>\n" +
            "  <meta charset=\"utf-8\">\n" +
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
            "  <title>Портфолио</title>\n" +
            "  <style>\n" +
            "    body { font-family: sans-serif; margin: 0; padding: 40px; background: #1e1f22; color: #ececec; }\n" +
            "    h1 { font-size: 36px; color: #00e5ff; }\n" +
            "    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }\n" +
            "    .item { background: #2a2b30; padding: 20px; border-radius: 8px; }\n" +
            "  </style>\n" +
            "</head>\n" +
            "<body>\n" +
            "  <h1>Портфолио</h1>\n" +
            "  <div class=\"grid\">\n" +
            "    <div class=\"item\">Проект 1</div>\n" +
            "    <div class=\"item\">Проект 2</div>\n" +
            "    <div class=\"item\">Проект 3</div>\n" +
            "  </div>\n" +
            "</body>\n" +
            "</html>";
}
