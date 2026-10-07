package com.sitebuilder.app;

import android.app.Activity;
import android.os.Bundle;
import android.widget.RadioButton;
import android.widget.RadioGroup;

public class SettingsActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        ThemeManager.applyTheme(this);
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);

        RadioGroup rg = findViewById(R.id.radioGroup);
        RadioButton rbDark = findViewById(R.id.radioDark);
        RadioButton rbBeige = findViewById(R.id.radioBeige);
        RadioButton rbLight = findViewById(R.id.radioLight);

        String current = ThemeManager.getTheme(this);
        if (current.equals(ThemeManager.THEME_BEIGE)) rbBeige.setChecked(true);
        else if (current.equals(ThemeManager.THEME_LIGHT)) rbLight.setChecked(true);
        else rbDark.setChecked(true);

        rg.setOnCheckedChangeListener(new RadioGroup.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(RadioGroup group, int checkedId) {
                String theme = ThemeManager.THEME_DARK;
                if (checkedId == R.id.radioBeige) theme = ThemeManager.THEME_BEIGE;
                else if (checkedId == R.id.radioLight) theme = ThemeManager.THEME_LIGHT;
                ThemeManager.setTheme(SettingsActivity.this, theme);
                ThemeManager.applyTheme(SettingsActivity.this);
                recreate();
            }
        });
    }
}
