package com.sitebuilder.app;

import android.os.Environment;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;

public class FileHelper {

    public static File getSaveDir() {
        File dir = new File(Environment.getExternalStoragePublicDirectory(
                Environment.DIRECTORY_DOCUMENTS), "SiteBuilder");
        if (!dir.exists()) dir.mkdirs();
        return dir;
    }

    public static boolean saveFile(String filename, String content) {
        try {
            File file = new File(getSaveDir(), filename);
            FileOutputStream fos = new FileOutputStream(file);
            fos.write(content.getBytes());
            fos.close();
            return true;
        } catch (IOException e) {
            e.printStackTrace();
            return false;
        }
    }

    public static String[] listFiles() {
        File dir = getSaveDir();
        File[] files = dir.listFiles();
        if (files == null) return new String[0];
        String[] names = new String[files.length];
        for (int i = 0; i < files.length; i++) {
            names[i] = files[i].getName();
        }
        return names;
    }

    public static String readFile(String filename) {
        try {
            File file = new File(getSaveDir(), filename);
            FileInputStream fis = new FileInputStream(file);
            byte[] data = new byte[(int) file.length()];
            fis.read(data);
            fis.close();
            return new String(data);
        } catch (IOException e) {
            e.printStackTrace();
            return "";
        }
    }
}
