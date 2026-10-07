package com.sitebuilder.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Toast;

public class MainActivity extends Activity {

    private EditText etHtml;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        ThemeManager.applyTheme(this);
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences("site_builder", MODE_PRIVATE);

        etHtml = findViewById(R.id.etHtml);
        Button btnPreview = findViewById(R.id.btnPreview);
        Button btnSave = findViewById(R.id.btnSave);
        Button btnOpen = findViewById(R.id.btnOpen);
        Button btnTemplate = findViewById(R.id.btnTemplate);
        Button btnClear = findViewById(R.id.btnClear);
        Button btnSettings = findViewById(R.id.btnSettings);

        // Загрузка черновика
        String draft = prefs.getString("draft_html", "");
        if (!draft.isEmpty()) {
            etHtml.setText(draft);
        } else {
            etHtml.setText(TemplateProvider.LANDING);
        }

        // Автосохранение черновика
        etHtml.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                prefs.edit().putString("draft_html", s.toString()).apply();
            }

            @Override
            public void afterTextChanged(Editable s) {}
        });

        // Просмотр
        btnPreview.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Intent intent = new Intent(MainActivity.this, PreviewActivity.class);
                intent.putExtra("html", etHtml.getText().toString());
                startActivity(intent);
            }
        });

        // Сохранить
        btnSave.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String filename = "index.html";
                boolean ok = FileHelper.saveFile(filename, etHtml.getText().toString());
                if (ok) {
                    Toast.makeText(MainActivity.this, R.string.file_saved, Toast.LENGTH_LONG).show();
                } else {
                    Toast.makeText(MainActivity.this, R.string.error_save, Toast.LENGTH_SHORT).show();
                }
            }
        });

        // Открыть
        btnOpen.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                final String[] files = FileHelper.listFiles();
                if (files.length == 0) {
                    Toast.makeText(MainActivity.this, "Нет сохранённых файлов", Toast.LENGTH_SHORT).show();
                    return;
                }
                AlertDialog.Builder b = new AlertDialog.Builder(MainActivity.this);
                b.setTitle("Открыть файл");
                b.setItems(files, new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface dialog, int which) {
                        String content = FileHelper.readFile(files[which]);
                        etHtml.setText(content);
                    }
                });
                b.show();
            }
        });

        // Шаблон
        btnTemplate.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                AlertDialog.Builder b = new AlertDialog.Builder(MainActivity.this);
                b.setTitle("Выберите шаблон");
                b.setItems(TemplateProvider.NAMES, new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface dialog, int which) {
                        etHtml.setText(TemplateProvider.getTemplate(which));
                    }
                });
                b.show();
            }
        });

        // Очистить
        btnClear.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                new AlertDialog.Builder(MainActivity.this)
                        .setMessage(R.string.confirm_clear)
                        .setPositiveButton(R.string.yes, new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface dialog, int which) {
                                etHtml.setText("");
                            }
                        })
                        .setNegativeButton(R.string.no, null)
                        .show();
            }
        });

        // Настройки (тема)
        btnSettings.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startActivity(new Intent(MainActivity.this, SettingsActivity.class));
            }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        // Переприменяем тему, если пользователь её поменял
        ThemeManager.applyTheme(this);
    }
          }
